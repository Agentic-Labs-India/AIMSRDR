from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


# Flat delivery layout (source of truth):
#   data/<date>/dem/*.tif + .tfw + .prj
#   data/<date>/ortho/*.ecw + .eww + .prj
FEB = Path("24 February")
MARCH = Path("3rd March")


@dataclass(frozen=True)
class SurveySpec:
    id: str
    label: str
    date: str
    stage: int
    dtm_rel: Path | None
    ortho_rel: Path | None
    piles_rel: Path | None = None
    volumes_rel: Path | None = None
    report_package: str | None = None
    is_primary: bool = False
    note: str | None = None


@dataclass
class SiteSpec:
    id: str
    name: str
    description: str
    crs: str = "EPSG:21037"  # Arc 1960 / UTM zone 37S (matches DEM PRJ)
    patio_dir: Path | None = None
    chainage_dir: Path | None = None
    patio_names: tuple[str, ...] = ()
    chainage_names: tuple[str, ...] = ()
    primary_compare_from: str = "report-24-feb"
    primary_compare_to: str = "report-3rd-march"
    surveys: list[SurveySpec] = field(default_factory=list)


def build_nacala_site() -> SiteSpec:
    """DEM + Ortho monitoring for Nacala Port & Coal Field."""
    return SiteSpec(
        id="nacala-coal-field",
        name="Nacala Port & Coal Field",
        description=(
            "DEM + Ortho monitoring. Each inspection date is powered by GeoTIFF DEM "
            "(TIF/TFW/PRJ) and Ortho (ECW/EWW/PRJ). Primary compare: 24 Feb vs 3rd March."
        ),
        surveys=[
            SurveySpec(
                id="report-24-feb",
                label="24 Feb Survey",
                date="2025-02-24",
                stage=4,
                report_package="24 February",
                is_primary=True,
                dtm_rel=FEB / "dem" / "Nacala-Port & Coal-Field Stage-4-1.tif",
                ortho_rel=FEB / "ortho" / "MOZAMBIQUE PORT & COAL FIELD 24-Feb.ecw",
                note="DEM (TIF/TFW/PRJ) + Ortho (ECW/EWW/PRJ) for 24 February inspection.",
            ),
            SurveySpec(
                id="report-3rd-march",
                label="3rd March Survey",
                date="2025-03-03",
                stage=6,
                report_package="3rd March",
                is_primary=True,
                dtm_rel=MARCH / "dem" / "Nacala-Port & Coal-Field Stage-6.tif",
                ortho_rel=MARCH / "ortho" / "MOZAMBIQUE PORT & COAL FIELD 03-March.ecw",
                note="DEM (TIF/TFW/PRJ) + Ortho (ECW/EWW/PRJ) for 3rd March inspection.",
            ),
        ],
    )


SITE_REGISTRY: dict[str, SiteSpec] = {
    "nacala-coal-field": build_nacala_site(),
}
