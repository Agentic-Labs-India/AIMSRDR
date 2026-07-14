from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AssetType(str, Enum):
    STOCKYARD = "stockyard"
    RIVER = "river"
    DAM = "dam"
    ROAD = "road"


class AssetKind(str, Enum):
    DTM = "dtm"
    ORTHO = "ortho"
    PILES = "piles"
    PATIO = "patio"
    CHAINAGE = "chainage"
    VOLUMES = "volumes"
    MESH = "mesh"
    TILES = "tiles"
    CHANGE_HEATMAP = "change_heatmap"


class AssetStatus(str, Enum):
    AVAILABLE = "available"
    MISSING = "missing"
    PENDING = "pending"
    PROCESSED = "processed"


class AssetRef(BaseModel):
    kind: AssetKind
    status: AssetStatus
    path: str | None = None
    url: str | None = None
    bytes: int | None = None
    note: str | None = None


class PileMetrics(BaseModel):
    id: str
    patio: str | None = None
    name: str | None = None
    total_volume_m3: float | None = None
    net_volume_m3: float | None = None
    cut_volume_m3: float | None = None
    fill_volume_m3: float | None = None
    enclosed_area_ha: float | None = None
    perimeter_m: float | None = None
    avg_elev_m: float | None = None
    min_elev_m: float | None = None
    max_elev_m: float | None = None
    centroid: list[float] | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class SurveySummary(BaseModel):
    net_volume_m3: float | None = None
    total_volume_m3: float | None = None
    cut_volume_m3: float | None = None
    fill_volume_m3: float | None = None
    enclosed_area_ha: float | None = None
    perimeter_km: float | None = None
    pile_count: int = 0
    named_pile_count: int = 0
    dem_min_m: float | None = None
    dem_max_m: float | None = None
    dem_mean_m: float | None = None
    area_km2: float | None = None
    gsd_cm: float | None = None
    dem_width_px: int | None = None
    dem_height_px: int | None = None


class RasterProducts(BaseModel):
    dem_preview_url: str | None = None
    dem_rgb_url: str | None = None
    dem_rgb_tif_url: str | None = None
    dem_heightmap_url: str | None = None
    dem_hillshade_url: str | None = None
    dem_scaled_url: str | None = None
    dem_meta_url: str | None = None
    ortho_preview_url: str | None = None
    ortho_meta_url: str | None = None
    ortho_status: str | None = None
    ortho_note: str | None = None
    dem_metadata: dict[str, Any] = Field(default_factory=dict)
    ortho_metadata: dict[str, Any] = Field(default_factory=dict)


class Survey(BaseModel):
    id: str
    label: str
    date: str
    stage: int
    crs: str = "EPSG:32737"
    report_package: str | None = None
    is_primary: bool = False
    assets: dict[str, AssetRef] = Field(default_factory=dict)
    summary: SurveySummary = Field(default_factory=SurveySummary)
    piles: list[PileMetrics] = Field(default_factory=list)
    piles_geojson_url: str | None = None
    rasters: RasterProducts = Field(default_factory=RasterProducts)


class PrimaryCompare(BaseModel):
    from_survey_id: str
    to_survey_id: str
    label: str = "24 Feb Report → 3rd March Report"


class Site(BaseModel):
    id: str
    name: str
    asset_type: AssetType
    crs: str = "EPSG:32737"
    country: str = "Mozambique"
    description: str
    patio_geojson_url: str | None = None
    chainage_geojson_url: str | None = None
    primary_compare: PrimaryCompare | None = None
    surveys: list[Survey] = Field(default_factory=list)


class PileDelta(BaseModel):
    id: str
    patio: str | None = None
    volume_from_m3: float | None = None
    volume_to_m3: float | None = None
    delta_m3: float | None = None
    area_from_ha: float | None = None
    area_to_ha: float | None = None
    delta_area_ha: float | None = None
    centroid: list[float] | None = None


class SurfaceDefect(BaseModel):
    id: str
    type: str  # pothole | rut | heave
    severity: str = "low"
    depth_m: float | None = None
    delta_m: float | None = None
    area_m2_approx: float | None = None
    pixel: list[int] | None = None
    easting: float | None = None
    northing: float | None = None


class DodProducts(BaseModel):
    preview_url: str | None = None
    stats_url: str | None = None
    defects_url: str | None = None
    stats: dict[str, Any] = Field(default_factory=dict)
    defects: dict[str, Any] = Field(default_factory=dict)


class Comparison(BaseModel):
    site_id: str
    from_survey_id: str
    to_survey_id: str
    cut_volume_m3: float | None = None
    fill_volume_m3: float | None = None
    net_delta_m3: float | None = None
    matched_piles: int = 0
    unmatched_from: list[str] = Field(default_factory=list)
    unmatched_to: list[str] = Field(default_factory=list)
    piles: list[PileDelta] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    dod: DodProducts = Field(default_factory=DodProducts)


class ProcessResult(BaseModel):
    ok: bool
    site_id: str
    surveys_processed: int
    output_dir: str
    messages: list[str] = Field(default_factory=list)


class ProcessJobStart(BaseModel):
    job_id: str
    site_id: str
    status: str
    progress: float = 0
    step: str = "Queued"


class ProcessJobStatus(BaseModel):
    job_id: str
    site_id: str
    status: str
    progress: float
    step: str
    messages: list[str] = Field(default_factory=list)
    error: str | None = None
    result: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    data_root: str
    processed_root: str
    data_root_exists: bool
    site_registered: bool
