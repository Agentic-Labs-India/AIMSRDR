from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings
from app.schemas import (
    AssetKind,
    AssetRef,
    AssetStatus,
    AssetType,
    DodProducts,
    PrimaryCompare,
    ProcessResult,
    RasterProducts,
    Site,
    Survey,
    SurveySummary,
)
from app.services.catalog import SITE_REGISTRY, SiteSpec, SurveySpec
from app.services.comparison import compare_surveys
from app.services.jobs import ProgressCallback
from app.services.raster import (
    gdal_available,
    process_dem,
    process_dod,
    process_ortho,
    resolve_ortho_source,
)
from app.services.shapefile_io import (
    merge_feature_collections,
    shapefile_complete,
    shapefile_to_geojson,
    write_geojson,
)
from app.services.volumes import (
    load_volumes,
    merge_volume_into_piles,
    piles_from_geojson_features,
)


def _rel_url(site_id: str, *parts: str) -> str:
    return "/api/v1/media/" + "/".join([site_id, *parts])


def _asset_from_path(
    kind: AssetKind,
    data_root: Path,
    rel: Path | None,
    *,
    processed_url: str | None = None,
    missing_note: str | None = None,
    pending_note: str | None = None,
) -> AssetRef:
    if rel is None:
        return AssetRef(kind=kind, status=AssetStatus.MISSING, note=missing_note)
    abs_path = data_root / rel
    if not abs_path.exists():
        return AssetRef(
            kind=kind,
            status=AssetStatus.MISSING,
            path=str(rel).replace("\\", "/"),
            note=missing_note or "File not found on disk",
        )
    status = AssetStatus.PROCESSED if processed_url else AssetStatus.AVAILABLE
    return AssetRef(
        kind=kind,
        status=status,
        path=str(rel).replace("\\", "/"),
        url=processed_url,
        bytes=abs_path.stat().st_size,
        note=pending_note,
    )


def _process_survey(
    settings: Settings,
    site: SiteSpec,
    spec: SurveySpec,
    out_dir: Path,
) -> tuple[Survey, list[str]]:
    messages: list[str] = []
    assets: dict[str, AssetRef] = {}

    rasters = RasterProducts()
    piles_geojson_url = None
    piles = []
    summary = SurveySummary()

    # --- DEM for every inspection date that has a GeoTIFF ---
    if spec.dtm_rel and (settings.data_root / spec.dtm_rel).exists() and gdal_available():
        try:
            dem_result = process_dem(
                settings.data_root / spec.dtm_rel,
                out_dir,
                spec.id,
                max_dim=1536 if spec.is_primary else 1024,
            )
            dem_meta = dem_result["metadata"]
            files = dem_result["files"]
            rasters.dem_metadata = dem_meta
            rasters.dem_preview_url = _rel_url(site.id, files["preview"])
            rasters.dem_rgb_url = _rel_url(site.id, files["rgb"])
            rasters.dem_rgb_tif_url = _rel_url(site.id, files["rgb_tif"])
            rasters.dem_heightmap_url = _rel_url(site.id, files["heightmap"])
            rasters.dem_hillshade_url = _rel_url(site.id, files["hillshade"])
            rasters.dem_scaled_url = _rel_url(site.id, files["scaled"])
            rasters.dem_meta_url = _rel_url(site.id, files["meta"])
            stats = dem_meta.get("elevation_stats") or {}
            summary.dem_min_m = stats.get("minimum")
            summary.dem_max_m = stats.get("maximum")
            summary.dem_mean_m = stats.get("mean")
            summary.area_km2 = dem_meta.get("area_km2")
            summary.gsd_cm = dem_meta.get("gsd_cm")
            summary.dem_width_px = dem_meta.get("width_px")
            summary.dem_height_px = dem_meta.get("height_px")
            assets["dtm"] = AssetRef(
                kind=AssetKind.DTM,
                status=AssetStatus.PROCESSED,
                path=str(spec.dtm_rel).replace("\\", "/"),
                url=rasters.dem_preview_url,
                bytes=(settings.data_root / spec.dtm_rel).stat().st_size,
                note="DEM preview + heightmap generated from GeoTIFF (+ TFW/PRJ).",
            )
            assets["mesh"] = AssetRef(
                kind=AssetKind.MESH,
                status=AssetStatus.PROCESSED,
                url=rasters.dem_heightmap_url,
                note="Heightmap ready for browser 3D displacement terrain.",
            )
            messages.append(f"{spec.id}: DEM products generated")
        except Exception as exc:  # noqa: BLE001
            assets["dtm"] = _asset_from_path(
                AssetKind.DTM,
                settings.data_root,
                spec.dtm_rel,
                pending_note=f"DEM present but processing failed: {exc}",
            )
            assets["mesh"] = AssetRef(kind=AssetKind.MESH, status=AssetStatus.PENDING, note=str(exc))
            messages.append(f"{spec.id}: DEM processing failed ({exc})")
    else:
        assets["dtm"] = _asset_from_path(
            AssetKind.DTM,
            settings.data_root,
            spec.dtm_rel,
            pending_note="DEM registered. Requires GDAL container for preview/heightmap generation.",
        )
        assets["mesh"] = AssetRef(
            kind=AssetKind.MESH,
            status=AssetStatus.PENDING,
            note="Heightmap pending GDAL DEM processing.",
        )

    # --- Ortho (true-color RGB). Prefer GeoTIFF / cached RGB; ECW needs QGIS convert. ---
    ortho_src = resolve_ortho_source(settings.data_root, spec.ortho_rel, out_dir, spec.id)
    if ortho_src is not None and gdal_available():
        ortho_result = process_ortho(ortho_src, out_dir, spec.id)
        rasters.ortho_status = ortho_result["status"]
        rasters.ortho_note = ortho_result.get("note")
        rasters.ortho_metadata = ortho_result.get("metadata") or {}
        files = ortho_result.get("files") or {}
        if files.get("preview"):
            rasters.ortho_preview_url = _rel_url(site.id, files["preview"])
        if files.get("meta"):
            rasters.ortho_meta_url = _rel_url(site.id, files["meta"])
        assets["ortho"] = AssetRef(
            kind=AssetKind.ORTHO,
            status=AssetStatus.PROCESSED if ortho_result["status"] == "processed" else AssetStatus.AVAILABLE,
            path=str(spec.ortho_rel).replace("\\", "/") if spec.ortho_rel else ortho_src.name,
            url=rasters.ortho_preview_url,
            bytes=ortho_src.stat().st_size,
            note=ortho_result.get("note") or "True-color RGB ortho preview.",
        )
        assets["tiles"] = AssetRef(
            kind=AssetKind.TILES,
            status=AssetStatus.PROCESSED if rasters.ortho_preview_url else AssetStatus.PENDING,
            url=rasters.ortho_preview_url,
            note="True-color ortho for 3D point cloud + imagery panels.",
        )
        messages.append(f"{spec.id}: ortho status={ortho_result['status']} src={ortho_src.name}")
    else:
        assets["ortho"] = _asset_from_path(
            AssetKind.ORTHO,
            settings.data_root,
            spec.ortho_rel,
            missing_note="Ortho missing",
            pending_note=(
                "Ortho ECW present but Docker GDAL cannot read ECW. "
                "Run scripts/convert_ortho_ecw.ps1 (uses QGIS ECW driver), then Process DEM/Ortho."
            ),
        )
        assets["tiles"] = AssetRef(kind=AssetKind.TILES, status=AssetStatus.PENDING)

    if spec.piles_rel and shapefile_complete(settings.data_root / spec.piles_rel):
        geojson = shapefile_to_geojson(settings.data_root / spec.piles_rel, feature_id_prefix=f"{spec.id}-")
        out_name = f"{spec.id}-piles.geojson"
        write_geojson(out_dir / out_name, geojson)
        piles_geojson_url = _rel_url(site.id, out_name)
        assets["piles"] = AssetRef(
            kind=AssetKind.PILES,
            status=AssetStatus.PROCESSED,
            path=str(spec.piles_rel).replace("\\", "/"),
            url=piles_geojson_url,
            bytes=(settings.data_root / spec.piles_rel).stat().st_size,
        )
        piles = piles_from_geojson_features(geojson["features"])
        summary.pile_count = len(piles)
        summary.named_pile_count = sum(1 for p in piles if p.name and str(p.name).upper().startswith("NC_"))
        areas = [p.enclosed_area_ha for p in piles if p.enclosed_area_ha is not None]
        if areas:
            summary.enclosed_area_ha = sum(areas)
        messages.append(f"{spec.id}: wrote {out_name} ({len(piles)} features)")
    else:
        assets["piles"] = AssetRef(
            kind=AssetKind.PILES,
            status=AssetStatus.MISSING,
            path=str(spec.piles_rel).replace("\\", "/") if spec.piles_rel else None,
            note="Pile shapefile missing or incomplete",
        )
        messages.append(f"{spec.id}: pile shapefile missing")

    if spec.volumes_rel:
        vol_path = settings.data_root / spec.volumes_rel
        if vol_path.exists() and vol_path.suffix.lower() in {".csv", ".xlsx", ".xlsm"}:
            try:
                volume_piles, vol_summary = load_volumes(vol_path)
                piles = merge_volume_into_piles(piles, volume_piles) if piles else volume_piles
                summary = vol_summary.model_copy(
                    update={
                        "pile_count": len(piles),
                        "named_pile_count": sum(
                            1 for p in piles if p.name and str(p.name).upper().startswith("NC_")
                        ),
                        "enclosed_area_ha": vol_summary.enclosed_area_ha or summary.enclosed_area_ha,
                    }
                )
                assets["volumes"] = AssetRef(
                    kind=AssetKind.VOLUMES,
                    status=AssetStatus.PROCESSED,
                    path=str(spec.volumes_rel).replace("\\", "/"),
                    bytes=vol_path.stat().st_size,
                )
                messages.append(f"{spec.id}: loaded {len(volume_piles)} volume rows from {vol_path.suffix}")
            except Exception as exc:  # noqa: BLE001
                assets["volumes"] = AssetRef(
                    kind=AssetKind.VOLUMES,
                    status=AssetStatus.AVAILABLE,
                    path=str(spec.volumes_rel).replace("\\", "/"),
                    bytes=vol_path.stat().st_size,
                    note=f"Volume file present but failed to parse: {exc}",
                )
                messages.append(f"{spec.id}: volume parse failed ({exc})")
        elif vol_path.exists():
            assets["volumes"] = AssetRef(
                kind=AssetKind.VOLUMES,
                status=AssetStatus.AVAILABLE,
                path=str(spec.volumes_rel).replace("\\", "/"),
                bytes=vol_path.stat().st_size,
            )
        else:
            assets["volumes"] = AssetRef(
                kind=AssetKind.VOLUMES,
                status=AssetStatus.MISSING,
                path=str(spec.volumes_rel).replace("\\", "/"),
            )
    else:
        assets["volumes"] = AssetRef(
            kind=AssetKind.VOLUMES,
            status=AssetStatus.MISSING,
            note="No independent volume sheet mapped for this survey",
        )

    if spec.note:
        messages.append(f"{spec.id}: {spec.note}")

    survey = Survey(
        id=spec.id,
        label=spec.label,
        date=spec.date,
        stage=spec.stage,
        crs=site.crs,
        report_package=spec.report_package,
        is_primary=spec.is_primary,
        assets=assets,
        summary=summary,
        piles=piles,
        piles_geojson_url=piles_geojson_url,
        rasters=rasters,
    )
    return survey, messages


def process_site(
    settings: Settings,
    site_id: str,
    progress_cb: ProgressCallback | None = None,
) -> ProcessResult:
    if site_id not in SITE_REGISTRY:
        raise KeyError(f"Unknown site_id: {site_id}")

    def report(progress: float, step: str, message: str | None = None) -> None:
        if progress_cb:
            progress_cb(progress, step if not message else f"{step}: {message}")

    site_spec = SITE_REGISTRY[site_id]
    out_dir = settings.processed_root / site_id
    out_dir.mkdir(parents=True, exist_ok=True)
    messages: list[str] = []
    report(2, "Preparing output")

    # Optional site vectors (not required for DEM/Ortho monitoring)
    patio_url = None
    patio_collections = []
    if site_spec.patio_dir and site_spec.patio_names:
        report(5, "Loading site vectors")
        for name in site_spec.patio_names:
            shp = settings.data_root / site_spec.patio_dir / f"{name}.shp"
            if shapefile_complete(shp):
                patio_collections.append(shapefile_to_geojson(shp, feature_id_prefix=f"{name}-"))
                messages.append(f"patio: loaded {name}")
        if patio_collections:
            patio_geo = merge_feature_collections(*patio_collections)
            write_geojson(out_dir / "patio.geojson", patio_geo)
            patio_url = _rel_url(site_id, "patio.geojson")

    chainage_url = None
    chainage_collections = []
    if site_spec.chainage_dir and site_spec.chainage_names:
        for name in site_spec.chainage_names:
            shp = settings.data_root / site_spec.chainage_dir / f"{name}.shp"
            if shapefile_complete(shp):
                chainage_collections.append(shapefile_to_geojson(shp, feature_id_prefix=f"{name}-"))
                messages.append(f"chainage: loaded {name}")
        if chainage_collections:
            chainage_geo = merge_feature_collections(*chainage_collections)
            write_geojson(out_dir / "chainage.geojson", chainage_geo)
            chainage_url = _rel_url(site_id, "chainage.geojson")

    surveys: list[Survey] = []
    survey_count = max(len(site_spec.surveys), 1)
    # Surveys occupy roughly 10% → 80% of the bar.
    for index, spec in enumerate(site_spec.surveys):
        base = 10 + (70 * index / survey_count)
        report(base, f"Processing DEM ({spec.label})")
        survey, survey_msgs = _process_survey(settings, site_spec, spec, out_dir)
        surveys.append(survey)
        messages.extend(survey_msgs)
        (out_dir / f"{survey.id}.json").write_text(
            survey.model_dump_json(indent=2),
            encoding="utf-8",
        )
        report(
            10 + (70 * (index + 1) / survey_count),
            f"Finished {spec.label}",
            message="DEM/Ortho products ready" if survey.rasters.dem_preview_url else None,
        )

    report(82, "Writing site package")
    site = Site(
        id=site_spec.id,
        name=site_spec.name,
        asset_type=AssetType.STOCKYARD,
        crs=site_spec.crs,
        description=site_spec.description,
        patio_geojson_url=patio_url,
        chainage_geojson_url=chainage_url,
        primary_compare=PrimaryCompare(
            from_survey_id=site_spec.primary_compare_from,
            to_survey_id=site_spec.primary_compare_to,
            label="24 Feb Report → 3rd March Report",
        ),
        surveys=surveys,
    )
    (out_dir / "site.json").write_text(site.model_dump_json(indent=2), encoding="utf-8")

    # Primary DEM compare (DoD). Additional pairs can be requested via the compare API.
    comparisons_dir = out_dir / "comparisons"
    comparisons_dir.mkdir(exist_ok=True)
    by_id = {s.id: s for s in surveys}
    pairs = [
        (site_spec.primary_compare_from, site_spec.primary_compare_to),
    ]
    for left_id, right_id in pairs:
        if left_id in by_id and right_id in by_id:
            report(88, "Building DEM of Difference", f"{left_id} → {right_id}")
            cmp = compare_surveys(site_id, by_id[left_id], by_id[right_id])
            left_spec = next((s for s in site_spec.surveys if s.id == left_id), None)
            right_spec = next((s for s in site_spec.surveys if s.id == right_id), None)
            if (
                gdal_available()
                and left_spec
                and right_spec
                and left_spec.dtm_rel
                and right_spec.dtm_rel
                and (settings.data_root / left_spec.dtm_rel).exists()
                and (settings.data_root / right_spec.dtm_rel).exists()
            ):
                try:
                    pair_id = f"{left_id}__{right_id}"
                    dod = process_dod(
                        settings.data_root / left_spec.dtm_rel,
                        settings.data_root / right_spec.dtm_rel,
                        out_dir,
                        pair_id=pair_id,
                    )
                    cmp.dod = DodProducts(
                        preview_url=_rel_url(site_id, dod["files"]["preview"]),
                        stats_url=_rel_url(site_id, dod["files"]["stats"]),
                        defects_url=_rel_url(site_id, dod["files"]["defects"])
                        if dod["files"].get("defects")
                        else None,
                        stats=dod["stats"],
                        defects=dod.get("defects") or {},
                    )
                    cmp.notes = [
                        *cmp.notes,
                        "DEM of Difference (DoD) generated from GeoTIFF DEMs.",
                        "Surface defect candidates (pothole/rut/heave) extracted from DoD extrema.",
                    ]
                    messages.append(f"DoD generated for {pair_id}")
                except Exception as exc:  # noqa: BLE001
                    cmp.notes = [*cmp.notes, f"DoD generation failed: {exc}"]
                    messages.append(f"DoD failed for {left_id}->{right_id}: {exc}")
            (comparisons_dir / f"{left_id}__{right_id}.json").write_text(
                cmp.model_dump_json(indent=2),
                encoding="utf-8",
            )

    messages.append(f"Wrote site package to {out_dir}")
    report(100, "Complete")
    return ProcessResult(
        ok=True,
        site_id=site_id,
        surveys_processed=len(surveys),
        output_dir=str(out_dir),
        messages=messages,
    )


def load_site(settings: Settings, site_id: str) -> Site:
    path = settings.processed_root / site_id / "site.json"
    if not path.exists():
        process_site(settings, site_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    return Site.model_validate(data)


def load_survey(settings: Settings, site_id: str, survey_id: str) -> Survey:
    path = settings.processed_root / site_id / f"{survey_id}.json"
    if not path.exists():
        process_site(settings, site_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    return Survey.model_validate(data)


def load_or_build_comparison(
    settings: Settings,
    site_id: str,
    from_id: str,
    to_id: str,
):
    from app.schemas import Comparison

    path = settings.processed_root / site_id / "comparisons" / f"{from_id}__{to_id}.json"
    if path.exists():
        cmp = Comparison.model_validate(json.loads(path.read_text(encoding="utf-8")))
        sample = (cmp.dod.stats or {}).get("sample_pixels") if cmp.dod else None
        has_defects = bool((cmp.dod.defects or {}).get("features")) if cmp.dod else False
        # Reuse cached compare only when DoD has overlap + defect candidates.
        if (cmp.dod.preview_url and sample and has_defects) or not gdal_available():
            return cmp

    left = load_survey(settings, site_id, from_id)
    right = load_survey(settings, site_id, to_id)
    cmp = compare_surveys(site_id, left, right)

    site_spec = SITE_REGISTRY[site_id]
    left_spec = next((s for s in site_spec.surveys if s.id == from_id), None)
    right_spec = next((s for s in site_spec.surveys if s.id == to_id), None)
    out_dir = settings.processed_root / site_id
    if (
        gdal_available()
        and left_spec
        and right_spec
        and left_spec.dtm_rel
        and right_spec.dtm_rel
        and (settings.data_root / left_spec.dtm_rel).exists()
        and (settings.data_root / right_spec.dtm_rel).exists()
    ):
        try:
            pair_id = f"{from_id}__{to_id}"
            dod = process_dod(
                settings.data_root / left_spec.dtm_rel,
                settings.data_root / right_spec.dtm_rel,
                out_dir,
                pair_id=pair_id,
            )
            cmp.dod = DodProducts(
                preview_url=_rel_url(site_id, dod["files"]["preview"]),
                stats_url=_rel_url(site_id, dod["files"]["stats"]),
                defects_url=_rel_url(site_id, dod["files"]["defects"])
                if dod["files"].get("defects")
                else None,
                stats=dod["stats"],
                defects=dod.get("defects") or {},
            )
            cmp.notes = [
                *cmp.notes,
                "DEM of Difference (DoD) generated from GeoTIFF DEMs.",
                "Surface defect candidates (pothole/rut/heave) extracted from DoD extrema.",
            ]
        except Exception as exc:  # noqa: BLE001
            cmp.notes = [*cmp.notes, f"DoD generation failed: {exc}"]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cmp.model_dump_json(indent=2), encoding="utf-8")
    return cmp
