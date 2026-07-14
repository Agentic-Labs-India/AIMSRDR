from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings
from app.services.processor import process_site


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    settings.processed_root.mkdir(parents=True, exist_ok=True)
    site_dir = settings.processed_root / settings.site_id
    site_json = site_dir / "site.json"
    dem_ready = site_dir / "report-24-feb-dem-preview.png"
    # Avoid reprocessing multi-GB DEMs on every container restart.
    if settings.data_root.exists() and settings.site_id and (not site_json.exists() or not dem_ready.exists()):
        try:
            process_site(settings, settings.site_id)
        except Exception as exc:  # noqa: BLE001
            print(f"[startup] process_site failed: {exc}")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
