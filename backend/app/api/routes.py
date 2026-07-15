from __future__ import annotations

import threading

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.config import Settings, get_settings
from app.schemas import (
    Comparison,
    HealthResponse,
    ProcessJobStart,
    ProcessJobStatus,
    ProcessResult,
    Site,
    Survey,
)
from app.services.catalog import SITE_REGISTRY
from app.services.jobs import JOB_STORE
from app.services.patio_report import load_or_build_report
from app.services.patio_upload_report import build_report_from_dem_ortho_paths
from app.services.processor import (
    load_or_build_comparison,
    load_site,
    load_survey,
    process_site,
)
from app.services.raster import gdal_available

router = APIRouter(prefix="/api/v1")

_MEDIA_TYPES = {
    ".geojson": "application/geo+json",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".pdf": "application/pdf",
}


@router.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        data_root=str(settings.data_root),
        processed_root=str(settings.processed_root),
        data_root_exists=settings.data_root.exists(),
        site_registered=settings.site_id in SITE_REGISTRY,
    )


@router.get("/capabilities")
def capabilities() -> dict:
    return {
        "gdal": gdal_available(),
        "products": [
            "dem_preview",
            "dem_rgb",
            "dem_heightmap",
            "ortho_preview",
            "dod",
            "patio_volume_pdf",
        ],
        "inputs": {
            "dem": [".tif", ".tfw", ".prj"],
            "ortho": [".ecw", ".eww", ".prj", ".tif"],
            "patios": ["named stockpile polygons NC_CY*", "stage volume JSON"],
        },
    }


@router.get("/sites/{site_id}/reports/patio-volumes")
def patio_volume_report(
    site_id: str,
    survey_id: str = Query("report-24-feb"),
    force: bool = Query(False),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Build / return coal patio loose-volume report (MatrixGeo-style PDF + JSON)."""
    if site_id not in SITE_REGISTRY:
        raise HTTPException(status_code=404, detail="Site not found")
    try:
        return load_or_build_report(settings, site_id, survey_id, force=force)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/sites/{site_id}/reports/patio-volumes/pdf")
def patio_volume_report_pdf(
    site_id: str,
    survey_id: str = Query("report-24-feb"),
    force: bool = Query(False),
    settings: Settings = Depends(get_settings),
):
    if site_id not in SITE_REGISTRY:
        raise HTTPException(status_code=404, detail="Site not found")
    try:
        bundle = load_or_build_report(settings, site_id, survey_id, force=force)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    pdf_path = Path(bundle["pdf_path"]) if bundle.get("pdf_path") else None
    if not pdf_path or not pdf_path.exists():
        raise HTTPException(status_code=500, detail="PDF was not generated")
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=pdf_path.name,
        headers={"Content-Disposition": f'attachment; filename="{pdf_path.name}"'},
    )


async def _save_upload_stream(upload: UploadFile, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as handle:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)


@router.post("/reports/patio-volumes/upload")
async def patio_volume_report_upload(
    dem_tif: UploadFile = File(..., description="DEM GeoTIFF (.tif)"),
    dem_tfw: UploadFile | None = File(None, description="DEM world file (.tfw)"),
    dem_prj: UploadFile | None = File(None, description="DEM projection (.prj)"),
    ortho_ecw: UploadFile | None = File(None, description="Ortho (.ecw)"),
    ortho_eww: UploadFile | None = File(None, description="Ortho world file (.eww)"),
    ortho_prj: UploadFile | None = File(None, description="Ortho projection (.prj)"),
    survey_date: str | None = Form(None, description="YYYY-MM-DD"),
    site_name: str = Form("Nacala Port & Coal Field"),
    settings: Settings = Depends(get_settings),
) -> dict:
    """
    Accept DEM/ortho files and start a background job.
    Poll GET /api/v1/reports/patio-volumes/jobs/{job_id} for progress + result.
    """
    dem_name = dem_tif.filename or "dem.tif"
    if Path(dem_name).suffix.lower() not in {".tif", ".tiff"}:
        raise HTTPException(status_code=400, detail="DEM must be the .tif / .tiff file")

    import uuid

    job_key = uuid.uuid4().hex[:12]
    job, _created = JOB_STORE.create(f"upload-{job_key}")
    staging = settings.processed_root / "_staging" / job.id
    staging.mkdir(parents=True, exist_ok=True)

    dem_path = staging / "dem.tif"
    await _save_upload_stream(dem_tif, dem_path)
    if dem_path.stat().st_size == 0:
        raise HTTPException(status_code=400, detail="DEM .tif is empty")

    if dem_tfw and dem_tfw.filename:
        await _save_upload_stream(dem_tfw, staging / "dem.tfw")
    if dem_prj and dem_prj.filename:
        await _save_upload_stream(dem_prj, staging / "dem.prj")

    ortho_path: Path | None = None
    if ortho_ecw and ortho_ecw.filename:
        ortho_path = staging / "ortho.ecw"
        await _save_upload_stream(ortho_ecw, ortho_path)
        if ortho_eww and ortho_eww.filename:
            await _save_upload_stream(ortho_eww, staging / "ortho.eww")
        if ortho_prj and ortho_prj.filename:
            await _save_upload_stream(ortho_prj, staging / "ortho.prj")

    def run_job() -> None:
        JOB_STORE.update(job.id, status="running", progress=1, step="Starting…")

        def on_progress(progress: float, step: str) -> None:
            JOB_STORE.update(job.id, progress=progress, step=step, message=step)

        try:
            result = build_report_from_dem_ortho_paths(
                settings,
                job_id=job_key,
                dem_path=dem_path,
                ortho_path=ortho_path,
                survey_date=survey_date,
                site_name=site_name,
                progress_cb=on_progress,
            )
            JOB_STORE.update(
                job.id,
                status="completed",
                progress=100,
                step="Complete",
                result=result,
            )
        except Exception as exc:  # noqa: BLE001
            JOB_STORE.update(
                job.id,
                status="failed",
                step="Failed",
                error=str(exc),
                message=f"Failed: {exc}",
            )

    threading.Thread(target=run_job, name=f"upload-{job.id}", daemon=True).start()

    return {
        "ok": True,
        "job_id": job.id,
        "status": job.status,
        "progress": job.progress,
        "step": "Uploading complete — processing in background",
        "poll_url": f"/api/v1/reports/patio-volumes/jobs/{job.id}",
    }


@router.get("/reports/patio-volumes/jobs/{job_id}")
def patio_volume_job_status(job_id: str) -> dict:
    job = JOB_STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@router.get("/sites", response_model=list[dict])
def list_sites(settings: Settings = Depends(get_settings)) -> list[dict]:
    result = []
    for site_id, spec in SITE_REGISTRY.items():
        processed = (settings.processed_root / site_id / "site.json").exists()
        result.append(
            {
                "id": site_id,
                "name": spec.name,
                "crs": spec.crs,
                "survey_count": len(spec.surveys),
                "processed": processed,
            }
        )
    return result


@router.get("/sites/{site_id}", response_model=Site)
def get_site(site_id: str, settings: Settings = Depends(get_settings)) -> Site:
    if site_id not in SITE_REGISTRY:
        raise HTTPException(status_code=404, detail="Site not found")
    return load_site(settings, site_id)


@router.get("/sites/{site_id}/surveys/{survey_id}", response_model=Survey)
def get_survey(
    site_id: str,
    survey_id: str,
    settings: Settings = Depends(get_settings),
) -> Survey:
    if site_id not in SITE_REGISTRY:
        raise HTTPException(status_code=404, detail="Site not found")
    try:
        return load_survey(settings, site_id, survey_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sites/{site_id}/compare", response_model=Comparison)
def compare(
    site_id: str,
    from_survey: str = Query(..., alias="from"),
    to_survey: str = Query(..., alias="to"),
    settings: Settings = Depends(get_settings),
) -> Comparison:
    if site_id not in SITE_REGISTRY:
        raise HTTPException(status_code=404, detail="Site not found")
    try:
        return load_or_build_comparison(settings, site_id, from_survey, to_survey)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sites/{site_id}/process", response_model=ProcessJobStart)
def reprocess(
    site_id: str,
    async_job: bool = Query(True, alias="async"),
    settings: Settings = Depends(get_settings),
):
    if site_id not in SITE_REGISTRY:
        raise HTTPException(status_code=404, detail="Site not found")

    # Legacy/sync mode kept for scripts: POST .../process?async=false
    if not async_job:
        result = process_site(settings, site_id)
        return ProcessJobStart(
            job_id="sync",
            site_id=site_id,
            status="completed",
            progress=100,
            step="Complete",
        )

    job, created = JOB_STORE.create(site_id)

    def run_job() -> None:
        JOB_STORE.update(job.id, status="running", progress=1, step="Starting")

        def on_progress(progress: float, step: str) -> None:
            JOB_STORE.update(job.id, progress=progress, step=step, message=step)

        try:
            result = process_site(settings, site_id, progress_cb=on_progress)
            JOB_STORE.update(
                job.id,
                status="completed",
                progress=100,
                step="Complete",
                result=result.model_dump(),
            )
        except Exception as exc:  # noqa: BLE001
            JOB_STORE.update(
                job.id,
                status="failed",
                step="Failed",
                error=str(exc),
                message=f"Failed: {exc}",
            )

    if created:
        threading.Thread(target=run_job, name=f"process-{site_id}", daemon=True).start()

    return ProcessJobStart(
        job_id=job.id,
        site_id=job.site_id,
        status=job.status,
        progress=job.progress,
        step=job.step,
    )


@router.get("/sites/{site_id}/process/{job_id}", response_model=ProcessJobStatus)
def process_status(site_id: str, job_id: str) -> ProcessJobStatus:
    if site_id not in SITE_REGISTRY:
        raise HTTPException(status_code=404, detail="Site not found")
    job = JOB_STORE.get(job_id)
    if not job or job.site_id != site_id:
        raise HTTPException(status_code=404, detail="Job not found")
    return ProcessJobStatus.model_validate(job.to_dict())


@router.get("/media/{site_id}/{filename}")
def media(
    site_id: str,
    filename: str,
    download: bool = Query(False),
    settings: Settings = Depends(get_settings),
):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = settings.processed_root / site_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Media not found")
    media_type = _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'} if download else None
    return FileResponse(path, media_type=media_type, headers=headers)
