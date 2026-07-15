"""Orchestrate patio volume report build (JSON + figures + PDF)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import Settings
from app.services.patio_report_data import (
    PatioVolumeReport,
    build_patio_volume_report,
    report_to_dict,
)
from app.services.patio_report_figures import generate_report_figures
from app.services.patio_report_pdf import build_patio_volume_pdf


def _dem_path_for_survey(out_dir: Path, survey_id: str) -> Path:
    for name in (
        f"{survey_id}-dem-scaled.tif",
        f"{survey_id}-dem-rgb.tif",
    ):
        path = out_dir / name
        if path.exists():
            return path
    raise FileNotFoundError(f"No DEM product for {survey_id} under {out_dir}")


def generate_patio_volume_report_bundle(
    settings: Settings,
    site_id: str,
    survey_id: str = "report-24-feb",
    *,
    build_pdf: bool = True,
) -> dict[str, Any]:
    report = build_patio_volume_report(settings, site_id, survey_id)
    site_dir = settings.processed_root / site_id
    fig_dir = site_dir / "reports" / f"patio-volumes-{survey_id}" / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    dem_path = _dem_path_for_survey(site_dir, survey_id)
    dem_rgb = site_dir / f"{survey_id}-dem-rgb.png"
    figures = generate_report_figures(
        report,
        dem_path=dem_path,
        out_dir=fig_dir,
        dem_rgb_path=dem_rgb if dem_rgb.exists() else None,
    )

    json_name = f"{survey_id}-patio-volumes.json"
    pdf_name = f"{survey_id}-loose-coal-volumes.pdf"
    json_path = site_dir / json_name
    payload = report_to_dict(report)
    payload["figures"] = {
        "strips": figures.get("strips", {}),
        "lsections": figures.get("lsections", {}),
        "overviews": figures.get("overviews", {}),
        "errors": figures.get("errors", []),
    }
    json_path.write_text(
        __import__("json").dumps(payload, indent=2),
        encoding="utf-8",
    )

    pdf_path: Path | None = None
    if build_pdf:
        pdf_path = site_dir / pdf_name
        build_patio_volume_pdf(report, figures, pdf_path)

    return {
        "ok": True,
        "site_id": site_id,
        "survey_id": survey_id,
        "report_dir": str(fig_dir.parent),
        "json_url": f"/api/v1/media/{site_id}/{json_name}",
        "pdf_url": f"/api/v1/media/{site_id}/{pdf_name}" if pdf_path else None,
        "pdf_path": str(pdf_path) if pdf_path else None,
        "json_path": str(json_path),
        "summary": {
            "total_volume_m3": report.total_volume_m3,
            "totals_by_patio": report.totals_by_patio,
            "pile_count": len(report.rows),
            "source_stage": report.source_stage,
        },
        "data": payload,
    }


def load_or_build_report(
    settings: Settings,
    site_id: str,
    survey_id: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    site_dir = settings.processed_root / site_id
    pdf_name = f"{survey_id}-loose-coal-volumes.pdf"
    json_name = f"{survey_id}-patio-volumes.json"
    pdf_path = site_dir / pdf_name
    json_path = site_dir / json_name
    if not force and pdf_path.exists() and json_path.exists():
        import json

        data = json.loads(json_path.read_text(encoding="utf-8"))
        return {
            "ok": True,
            "cached": True,
            "site_id": site_id,
            "survey_id": survey_id,
            "report_dir": str(site_dir / "reports" / f"patio-volumes-{survey_id}"),
            "json_url": f"/api/v1/media/{site_id}/{json_name}",
            "pdf_url": f"/api/v1/media/{site_id}/{pdf_name}",
            "pdf_path": str(pdf_path),
            "json_path": str(json_path),
            "summary": {
                "total_volume_m3": data.get("total_volume_m3"),
                "totals_by_patio": data.get("totals_by_patio"),
                "pile_count": sum(
                    len((p or {}).get("piles") or []) for p in (data.get("patios") or {}).values()
                ),
                "source_stage": data.get("source_stage"),
            },
            "data": data,
        }
    return generate_patio_volume_report_bundle(
        settings, site_id, survey_id, build_pdf=True
    )
