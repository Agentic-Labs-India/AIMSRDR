"""Build patio volume PDF + DEM dashboard products from user DEM/ortho files."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from app.config import Settings
from app.services.detect_stockpiles import detect_stockpiles_from_dem
from app.services.patio_classify import (
    chainage_ranges_for_patio,
    classify_product,
    parse_avg_slope,
    patio_label,
    pile_height_m,
    sort_pile_name,
)
from app.services.patio_dem_volumes import compute_pile_metrics_from_dem
from app.services.patio_report_data import PatioPileRow, PatioVolumeReport, report_to_dict
from app.services.patio_report_figures import generate_report_figures
from app.services.patio_report_pdf import build_patio_volume_pdf
from app.services.raster import process_dem
from app.services.shapefile_io import write_geojson
from app.services.volumes import patio_from_pile_id, piles_from_geojson_features

ProgressCb = Callable[[float, str], None]


def _progress(cb: ProgressCb | None, pct: float, step: str) -> None:
    if cb:
        cb(pct, step)


def build_report_from_dem_ortho_paths(
    settings: Settings,
    *,
    job_id: str,
    dem_path: Path,
    ortho_path: Path | None = None,
    survey_date: str | None = None,
    site_name: str = "Nacala Port & Coal Field",
    progress_cb: ProgressCb | None = None,
) -> dict[str, Any]:
    """Run detection + volumes + PDF + DEM preview products. Uses on-disk paths."""
    out_dir = settings.processed_root / f"upload-{job_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Copy dem into out_dir with sidecars if present beside dem_path
    dem_local = out_dir / "dem.tif"
    if dem_path.resolve() != dem_local.resolve():
        shutil.copy2(dem_path, dem_local)
        for suffix in (".tfw", ".prj", ".tiff"):
            side = dem_path.with_suffix(suffix)
            if side.exists() and suffix != ".tiff":
                shutil.copy2(side, out_dir / f"dem{suffix}")
    dem_path = dem_local

    ortho_note = None
    if ortho_path and ortho_path.exists():
        ortho_local = out_dir / "ortho.ecw"
        if ortho_path.resolve() != ortho_local.resolve():
            shutil.copy2(ortho_path, ortho_local)
            for suffix in (".eww", ".prj"):
                side = ortho_path.with_suffix(suffix)
                if side.exists():
                    shutil.copy2(side, out_dir / f"ortho{suffix}")
        ortho_note = (
            "Ortho ECW sidecars saved. Docker GDAL often cannot decode ECW; "
            "3D uses DEM products."
        )

    _progress(progress_cb, 8, "Building DEM previews (heightmap / hillshade / RGB)…")
    dem_products = process_dem(dem_path, out_dir, "survey", max_dim=1280)
    scaled = out_dir / dem_products["files"]["scaled"]

    _progress(progress_cb, 28, "Detecting stockpiles from DEM…")
    # Detect on scaled DEM for speed
    detected = detect_stockpiles_from_dem(scaled if scaled.exists() else dem_path)
    geo = {
        "type": "FeatureCollection",
        "features": detected["features"],
        "crs": detected.get("crs"),
    }
    write_geojson(out_dir / "detected-piles.geojson", geo)
    if not geo["features"]:
        raise ValueError("DEM stockpile detection returned no piles")

    _progress(progress_cb, 48, f"Computing volumes for {len(geo['features'])} piles…")
    dem_metrics = compute_pile_metrics_from_dem(
        scaled if scaled.exists() else dem_path,
        geo,
        pile_crs=detected.get("meta", {}).get("dem_crs"),
    )
    if not dem_metrics:
        raise ValueError("Could not compute volumes for detected piles")

    geo_features = []
    for m in dem_metrics:
        geo_features.append(
            {
                "type": "Feature",
                "properties": {
                    **(m.get("properties") or {}),
                    "NAME": m["name"],
                    "feature_id": m["id"],
                    "area_ha": m.get("enclosed_area_ha"),
                    "MIN_ELEV_M": m.get("min_elev_m"),
                    "MAX_ELEV_M": m.get("max_elev_m"),
                    "AVG_ELEV_M": m.get("avg_elev_m"),
                },
                "geometry": m.get("geometry"),
            }
        )

    geo_piles = piles_from_geojson_features(geo_features)
    dem_by_name = {str(m["name"]).upper(): m for m in dem_metrics}
    for gp in geo_piles:
        m = dem_by_name.get(str(gp.name or gp.id).upper())
        if not m:
            continue
        gp.net_volume_m3 = m["net_volume_m3"]
        gp.total_volume_m3 = m["net_volume_m3"]
        gp.enclosed_area_ha = m.get("enclosed_area_ha")
        gp.min_elev_m = m.get("min_elev_m")
        gp.max_elev_m = m.get("max_elev_m")
        gp.avg_elev_m = m.get("avg_elev_m")
        gp.patio = m.get("patio") or gp.patio
        gp.properties = {**(gp.properties or {}), **(m.get("properties") or {})}

    geom_by_name = {
        str((f.get("properties") or {}).get("NAME")).upper(): f.get("geometry")
        for f in geo_features
    }

    date_iso = survey_date or datetime.utcnow().strftime("%Y-%m-%d")
    try:
        date_display = datetime.strptime(date_iso, "%Y-%m-%d").strftime("%d-%b-%y")
    except ValueError:
        date_display = date_iso
        date_iso = datetime.utcnow().strftime("%Y-%m-%d")

    chainage_maps = {
        patio: chainage_ranges_for_patio(geo_features, patio) for patio in ("A", "B", "C")
    }

    rows: list[PatioPileRow] = []
    for pile in sorted(geo_piles, key=lambda p: sort_pile_name(str(p.name or p.id))):
        name = str(pile.name or pile.id).upper()
        if not name.startswith("NC_") or pile.net_volume_m3 is None:
            continue
        patio = (pile.patio or patio_from_pile_id(name) or "?").upper()
        height = pile_height_m(pile.min_elev_m, pile.max_elev_m)
        slope = parse_avg_slope(pile.properties or {})
        product, morph = classify_product(
            patio,
            avg_slope_deg=slope,
            pile_height_m=height,
            net_volume_m3=float(pile.net_volume_m3),
        )
        show_hr = morph == "stockpile"
        ch = chainage_maps.get(patio, {}).get(name)
        ch_start, ch_end, ch_label = ch if ch else (0.0, 0.0, "—")
        rows.append(
            PatioPileRow(
                patio=patio,
                patio_name=patio_label(patio),
                pile_name=name,
                survey_date=date_iso,
                survey_date_display=date_display,
                net_volume_m3=float(pile.net_volume_m3),
                enclosed_area_ha=pile.enclosed_area_ha,
                chainage=ch_label,
                chainage_start_m=float(ch_start),
                chainage_end_m=float(ch_end),
                product=product,
                morph_class=morph,
                max_height_m=height if show_hr else None,
                avg_angle_repose_deg=slope if show_hr else None,
                show_height_repose=show_hr,
                min_elev_m=pile.min_elev_m,
                max_elev_m=pile.max_elev_m,
                centroid=pile.centroid,
                geometry=geom_by_name.get(name),
                properties=pile.properties or {},
            )
        )

    if not rows:
        raise ValueError("No pile rows could be built from the DEM.")

    by_patio: dict[str, list[PatioPileRow]] = {}
    for row in rows:
        by_patio.setdefault(row.patio, []).append(row)
    totals = {p: sum(r.net_volume_m3 for r in rs) for p, rs in by_patio.items()}

    notes = [
        "Inputs: user-selected DEM (.tif + .tfw + .prj) and optional ortho (.ecw + .eww + .prj).",
        "Stockpiles auto-detected from DEM (nDSM).",
        "Volumes computed from DEM inside each detected pile polygon.",
    ]
    if ortho_note:
        notes.append(ortho_note)

    report = PatioVolumeReport(
        site_id=f"upload-{job_id}",
        site_name=site_name,
        survey_id="survey",
        survey_label="DEM upload",
        survey_date=date_iso,
        survey_date_display=date_display,
        source_stage="dem_auto_detect",
        crs=detected.get("meta", {}).get("dem_crs") or "EPSG:21037",
        rows=rows,
        by_patio=by_patio,
        totals_by_patio=totals,
        total_volume_m3=sum(totals.values()),
        notes=notes,
    )

    _progress(progress_cb, 70, "Rendering report figures…")
    fig_dir = out_dir / "figures"
    figures = generate_report_figures(
        report,
        dem_path=scaled if scaled.exists() else dem_path,
        out_dir=fig_dir,
    )

    _progress(progress_cb, 88, "Writing PDF…")
    pdf_path = out_dir / "loose-coal-volumes.pdf"
    build_patio_volume_pdf(report, figures, pdf_path)
    payload = report_to_dict(report)
    payload["figures"] = figures
    payload["job_id"] = job_id
    payload["detection"] = detected.get("meta")
    payload["ortho_note"] = ortho_note
    json_path = out_dir / "patio-volumes.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    media_base = f"/api/v1/media/upload-{job_id}"
    elev = (dem_products.get("metadata") or {}).get("elevation_stats") or {}
    rasters = {
        "dem_preview_url": f"{media_base}/{dem_products['files']['preview']}",
        "dem_rgb_url": f"{media_base}/{dem_products['files']['rgb']}",
        "dem_rgb_tif_url": f"{media_base}/{dem_products['files']['rgb_tif']}",
        "dem_heightmap_url": f"{media_base}/{dem_products['files']['heightmap']}",
        "dem_hillshade_url": f"{media_base}/{dem_products['files']['hillshade']}",
        "dem_scaled_url": f"{media_base}/{dem_products['files']['scaled']}",
        "dem_meta_url": f"{media_base}/{dem_products['files']['meta']}",
        "dem_metadata": dem_products.get("metadata") or {},
        "ortho_status": ortho_note or "not_provided",
    }

    _progress(progress_cb, 100, "Complete")
    return {
        "ok": True,
        "job_id": job_id,
        "site_id": f"upload-{job_id}",
        "survey_id": "survey",
        "pdf_url": f"{media_base}/{pdf_path.name}",
        "json_url": f"{media_base}/{json_path.name}",
        "pdf_path": str(pdf_path),
        "json_path": str(json_path),
        "piles_geojson_url": f"{media_base}/detected-piles.geojson",
        "summary": {
            "total_volume_m3": report.total_volume_m3,
            "totals_by_patio": report.totals_by_patio,
            "pile_count": len(report.rows),
            "source_stage": report.source_stage,
            "dem_min_m": elev.get("minimum"),
            "dem_max_m": elev.get("maximum"),
            "dem_mean_m": elev.get("mean"),
        },
        "rasters": rasters,
        "data": payload,
        "ortho_note": ortho_note,
        "figure_errors": figures.get("errors") or [],
        "detection": detected.get("meta"),
    }


# Back-compat name used by older imports
def build_report_from_dem_ortho(*args: Any, **kwargs: Any) -> dict[str, Any]:
    raise RuntimeError("Use async upload job endpoint (build_report_from_dem_ortho_paths)")
