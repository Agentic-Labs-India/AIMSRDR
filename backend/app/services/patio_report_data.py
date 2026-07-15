"""Assemble patio volume report rows from processed Nacala survey artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import Settings
from app.services.patio_classify import (
    chainage_ranges_for_patio,
    classify_product,
    parse_avg_slope,
    patio_label,
    pile_height_m,
    sort_pile_name,
)
from app.services.volumes import patio_from_pile_id


@dataclass
class PatioPileRow:
    patio: str
    patio_name: str
    pile_name: str
    survey_date: str
    survey_date_display: str
    net_volume_m3: float
    enclosed_area_ha: float | None
    chainage: str
    chainage_start_m: float
    chainage_end_m: float
    product: str
    morph_class: str
    max_height_m: float | None
    avg_angle_repose_deg: float | None
    show_height_repose: bool
    min_elev_m: float | None = None
    max_elev_m: float | None = None
    centroid: list[float] | None = None
    geometry: dict[str, Any] | None = None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class PatioVolumeReport:
    site_id: str
    site_name: str
    survey_id: str
    survey_label: str
    survey_date: str
    survey_date_display: str
    source_stage: str
    crs: str
    rows: list[PatioPileRow]
    by_patio: dict[str, list[PatioPileRow]]
    totals_by_patio: dict[str, float]
    total_volume_m3: float
    notes: list[str] = field(default_factory=list)


_STAGE_BY_SURVEY = {
    "report-24-feb": ("stage-3", "24-Feb-25"),
    "report-3rd-march": ("stage-6", "03-Mar-25"),
}


def _display_date(iso_date: str, fallback: str) -> str:
    try:
        return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d-%b-%y")
    except ValueError:
        return fallback


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _count_named_nc(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        data = _load_json(path)
    except Exception:  # noqa: BLE001
        return 0
    if path.suffix.lower() == ".geojson" or "features" in data:
        return sum(
            1
            for f in data.get("features") or []
            if str((f.get("properties") or {}).get("NAME") or "").upper().startswith("NC_")
        )
    return sum(1 for p in data.get("piles") or [] if str(p.get("name") or "").upper().startswith("NC_"))


def _resolve_stage_paths(out_dir: Path, survey_id: str) -> tuple[Path, Path, str]:
    """Prefer survey stage artifacts; fall back to stage-3 named NC_CY* stockpiles."""
    stage_id, _ = _STAGE_BY_SURVEY.get(survey_id, ("stage-3", "24-Feb-25"))
    stage_json = out_dir / f"{stage_id}.json"
    stage_piles = out_dir / f"{stage_id}-piles.geojson"
    if not stage_json.exists():
        alt = out_dir / f"{survey_id}.json"
        if alt.exists():
            stage_json = alt
    if not stage_piles.exists():
        alt_piles = out_dir / f"{survey_id}-piles.geojson"
        if alt_piles.exists():
            stage_piles = alt_piles

    # March / unnamed polygon deliveries: reuse stage-3 named patio inventory
    if _count_named_nc(stage_json) == 0 or _count_named_nc(stage_piles) == 0:
        stage_json = out_dir / "stage-3.json"
        stage_piles = out_dir / "stage-3-piles.geojson"
        stage_id = "stage-3"
    return stage_json, stage_piles, stage_id


def build_patio_volume_report(
    settings: Settings,
    site_id: str,
    survey_id: str = "report-24-feb",
) -> PatioVolumeReport:
    out_dir = settings.processed_root / site_id
    stage_json_path, piles_path, stage_id = _resolve_stage_paths(out_dir, survey_id)
    if not stage_json_path.exists() or not piles_path.exists():
        raise FileNotFoundError(
            f"Patio volume inputs missing under {out_dir}. "
            "Need stage-*-piles.geojson and stage-*.json with named NC_CY* piles."
        )

    stage = _load_json(stage_json_path)
    geo = _load_json(piles_path)
    features = geo.get("features") or []
    stage_piles = {str(p.get("name") or p.get("id")).upper(): p for p in (stage.get("piles") or [])}

    # Survey metadata
    site_path = out_dir / "site.json"
    site_name = "Nacala Port & Coal Field"
    survey_label = survey_id
    survey_date = "2025-02-24"
    crs = "EPSG:21037"
    if site_path.exists():
        site = _load_json(site_path)
        site_name = site.get("name") or site_name
        crs = site.get("crs") or crs
        for s in site.get("surveys") or []:
            if s.get("id") == survey_id:
                survey_label = s.get("label") or survey_label
                survey_date = s.get("date") or survey_date
                break

    _, default_display = _STAGE_BY_SURVEY.get(survey_id, ("stage-3", "24-Feb-25"))
    date_display = _display_date(survey_date, default_display)

    # Chainage per patio from geometry
    chainage_maps: dict[str, dict[str, tuple[float, float, str]]] = {}
    for patio in ("A", "B", "C"):
        chainage_maps[patio] = chainage_ranges_for_patio(features, patio)

    feat_by_name = {}
    for feature in features:
        props = feature.get("properties") or {}
        name = str(props.get("NAME") or props.get("name") or "").upper()
        if name.startswith("NC_"):
            feat_by_name[name] = feature

    rows: list[PatioPileRow] = []
    notes = [
        "Volumes from survey stockpile calculation sheet / RAW metrics retained in processed stage JSON.",
        "Maximum pile height = max DEM elev − min DEM elev inside each patio polygon.",
        "Avg. angle of repose = average surface slope (°) from stockpile attributes.",
        "Product class from morphometric deep classification (lining pad vs stockpile grade).",
        "Chainage along patio long axis; MatrixGeo L-section labels used where known.",
    ]

    names = sorted(set(stage_piles) | set(feat_by_name), key=sort_pile_name)
    for name in names:
        if not name.startswith("NC_CY"):
            continue
        stage_row = stage_piles.get(name) or {}
        feature = feat_by_name.get(name)
        props = dict((feature or {}).get("properties") or {})
        props.update(stage_row.get("properties") or {})

        patio = stage_row.get("patio") or patio_from_pile_id(name) or "?"
        patio = str(patio).upper()
        net = stage_row.get("net_volume_m3")
        if net is None:
            continue
        area = stage_row.get("enclosed_area_ha")
        if area is None:
            area = props.get("area_ha") or props.get("ENCLOSED_A")
            try:
                area = float(str(area).replace("ha", "").strip()) if area is not None else None
            except ValueError:
                area = None

        min_e = stage_row.get("min_elev_m")
        max_e = stage_row.get("max_elev_m")
        if min_e is None:
            min_e = props.get("MIN_ELEV_M")
        if max_e is None:
            max_e = props.get("MAX_ELEV_M")
        try:
            min_e = float(min_e) if min_e is not None else None
            max_e = float(max_e) if max_e is not None else None
        except (TypeError, ValueError):
            min_e = max_e = None

        height = pile_height_m(min_e, max_e)
        slope = parse_avg_slope(props)
        product, morph = classify_product(
            patio,
            avg_slope_deg=slope,
            pile_height_m=height,
            net_volume_m3=float(net),
        )
        show_hr = morph == "stockpile"

        ch = chainage_maps.get(patio, {}).get(name)
        if ch:
            ch_start, ch_end, ch_label = ch
        else:
            ch_start = ch_end = 0.0
            ch_label = "—"

        centroid = stage_row.get("centroid")
        if not centroid and feature:
            # leave None; figures can compute
            centroid = None

        rows.append(
            PatioPileRow(
                patio=patio,
                patio_name=patio_label(patio),
                pile_name=name,
                survey_date=survey_date,
                survey_date_display=date_display,
                net_volume_m3=float(net),
                enclosed_area_ha=float(area) if area is not None else None,
                chainage=ch_label,
                chainage_start_m=float(ch_start),
                chainage_end_m=float(ch_end),
                product=product,
                morph_class=morph,
                max_height_m=height if show_hr else None,
                avg_angle_repose_deg=slope if show_hr else None,
                show_height_repose=show_hr,
                min_elev_m=min_e,
                max_elev_m=max_e,
                centroid=centroid,
                geometry=(feature or {}).get("geometry"),
                properties=props,
            )
        )

    rows.sort(key=lambda r: (r.patio, sort_pile_name(r.pile_name)))
    by_patio: dict[str, list[PatioPileRow]] = {}
    for row in rows:
        by_patio.setdefault(row.patio, []).append(row)
    totals = {p: sum(r.net_volume_m3 for r in rs) for p, rs in by_patio.items()}

    return PatioVolumeReport(
        site_id=site_id,
        site_name=site_name,
        survey_id=survey_id,
        survey_label=survey_label,
        survey_date=survey_date,
        survey_date_display=date_display,
        source_stage=stage_id,
        crs=crs,
        rows=rows,
        by_patio=by_patio,
        totals_by_patio=totals,
        total_volume_m3=sum(totals.values()),
        notes=notes,
    )


def report_to_dict(report: PatioVolumeReport) -> dict[str, Any]:
    return {
        "site_id": report.site_id,
        "site_name": report.site_name,
        "survey_id": report.survey_id,
        "survey_label": report.survey_label,
        "survey_date": report.survey_date,
        "survey_date_display": report.survey_date_display,
        "source_stage": report.source_stage,
        "crs": report.crs,
        "total_volume_m3": report.total_volume_m3,
        "totals_by_patio": report.totals_by_patio,
        "notes": report.notes,
        "patios": {
            patio: {
                "total_volume_m3": report.totals_by_patio.get(patio, 0.0),
                "pile_count": len(rows),
                "piles": [
                    {
                        "name": r.patio_name,
                        "pile_name": r.pile_name,
                        "date_of_survey": r.survey_date_display,
                        "net_volume_m3": round(r.net_volume_m3, 2),
                        "enclosed_area_ha": (
                            round(r.enclosed_area_ha, 3) if r.enclosed_area_ha is not None else None
                        ),
                        "chainage": r.chainage,
                        "product": r.product,
                        "morph_class": r.morph_class,
                        "maximum_height_m": (
                            round(r.max_height_m, 4) if r.max_height_m is not None else None
                        ),
                        "avg_angle_of_repose_deg": (
                            round(r.avg_angle_repose_deg, 2)
                            if r.avg_angle_repose_deg is not None
                            else None
                        ),
                    }
                    for r in rows
                ],
            }
            for patio, rows in report.by_patio.items()
        },
    }
