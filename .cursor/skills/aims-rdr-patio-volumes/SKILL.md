---
name: aims-rdr-patio-volumes
description: >-
  Build and fix Nacala coal patio volume detection, MatrixGeo-style PDF reports,
  L-section profiles, DEM strips, and patio classification. Use when the user
  mentions patio volumes, loose coal, stockpiles, NC_CY piles, chainage,
  L-sections, MatrixGeo PDF, or coalmine volume reports (not road potholes).
---

# AIMS RDR Patio Volume Reports

## Read first

1. Repo root `llm.txt` — CRS, data layout, APIs, known failures
2. Repo root `skills.md` — playbooks

## Hard rules

- This site is **coal patios / stockpiles**, never road potholes.
- Pile polygons are **EPSG:32737**; DEM products are **EPSG:21037**. Always warp before DEM sampling.
- Empty L-section grids or flat grey plans almost always mean a CRS miss.
- After figure code changes, regenerate with `force=true` (do not serve stale PDF).

## Implementation map

| Task | Module |
|------|--------|
| Product / lining / chainage | `backend/app/services/patio_classify.py` |
| Report rows | `backend/app/services/patio_report_data.py` |
| Figures | `backend/app/services/patio_report_figures.py` |
| PDF layout | `backend/app/services/patio_report_pdf.py` |
| Bundle | `backend/app/services/patio_report.py` |
| Routes | `backend/app/api/routes.py` |
| UI | `frontend/.../monitoring-dashboard.tsx` Patio Volumes |

## Regenerate

```bash
docker exec -e PYTHONPATH=/app aims-rdr-api python -c "from app.config import get_settings; from app.services.patio_report import generate_patio_volume_report_bundle; print(generate_patio_volume_report_bundle(get_settings(),'nacala-coal-field','report-24-feb',build_pdf=True)['pdf_path'])"
```

## Accept

- Distinct patio A/B/C strips
- Red elevation curve on L-section left
- Hillshade (not flat grey) on L-section right
