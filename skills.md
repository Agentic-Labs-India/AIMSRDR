# AIMS RDR — Agent Skills & Development Playbook

Use this file when extending coal patio volume detection, DEM/ortho monitoring, or MatrixGeo-style PDF reports.

## Skill: Patio volume PDF report (upload-first)

**When to use:** User asks for loose coal volumes, patio reports, MatrixGeo PDF, L-sections, stockpile chainage, or product classification (not road potholes).

**Primary UX (current):** Single page at `/` — user selects **files** (not folders):
1. DEM package: `.tif` + `.tfw` + `.prj` (required tif; sidecars recommended)
2. Ortho package (optional): `.ecw` + `.eww` + `.prj`
3. Generate → auto-detect stockpiles from DEM → PDF download

**Do:**
1. Read `llm.txt` for architecture, CRS rules, and data layout.
2. Do **not** require shapefiles / volume sheets — detect piles from DEM nDSM.
3. Save DEM/ortho sidecars with matching stems so GDAL georefs correctly.
4. Compute volumes from DEM above P5 base inside each detected polygon.
5. ECW may not open inside Docker GDAL — report still runs from DEM.
6. Verify L-section PNGs contain a red profile curve and patio strips differ per A/B/C.

**Don’t:**
- Frame features as road potholes/ruts/heave for this site.
- Sample DEM using raw polygon coordinates without CRS warp.
- Depend on deleted `stage-3.json` in processed/.

**Key modules:**
- `backend/app/services/patio_upload_report.py` — upload → report
- `backend/app/services/patio_dem_volumes.py` — DEM volumes
- `backend/app/services/patio_classify.py` — product / lining / chainage
- `backend/app/services/patio_report_figures.py` — DEM strip, L-section, overview
- `backend/app/services/patio_report_pdf.py` — ReportLab PDF layout
- API: `POST /api/v1/reports/patio-volumes/upload`
- UI: `/` → `PatioReportStudio`

## Skill: DEM / Ortho monitoring dashboard

**When to use:** 3D point cloud/mesh, DoD change, DEM RGB, ortho preview.

**Do:**
- Serve media via `/api/v1/media/{site}/{file}` with CORS for `localhost:3000`.
- 3D mesh must be built from DEM heightmap samples (CPU grid), not fragile GPU displacementMap alone.
- Ortho texture for 3D; elevation heatmap only for DoD / report strips.

**Key modules:**
- `backend/app/services/raster.py`, `processor.py`, `catalog.py`
- `frontend/src/components/survey/dem-terrain-scene.tsx`
- `frontend/src/components/survey/monitoring-dashboard.tsx`

## Skill: CRS & volume truth

| Asset | CRS |
|-------|-----|
| DEM TIF / scaled DEM | EPSG:21037 (Arc 1960 / UTM 37S) |
| Stockpile polygons (stage-*-piles) | EPSG:32737 (WGS 84 / UTM 37S) |
| Ortho ECW package | Often WGS84 UTM 37S |

**Volumes:** Named pile net volumes live in `stage-3.json` (RAW survey metrics). MatrixGeo “Final Sheet” XLSX may differ slightly if restored later via `volumes.py` + `openpyxl`.

**Heights / repose:**
- Max pile height = `max_elev − min_elev` inside polygon
- Angle of repose ≈ `AVG_SLOPE_` (blank for lining pads)

## Skill: Regenerate report after figure fixes

```bash
docker exec -e PYTHONPATH=/app aims-rdr-api python -c "from app.config import get_settings; from app.services.patio_report import generate_patio_volume_report_bundle; print(generate_patio_volume_report_bundle(get_settings(),'nacala-coal-field','report-24-feb',build_pdf=True)['pdf_path'])"
```

Or UI: Patio Volumes → Generate PDF (calls `force=true`).

Output: `backend/processed/nacala-coal-field/report-24-feb-loose-coal-volumes.pdf`

## Skill: Local run

```bash
docker compose up --build -d   # API :8000
cd frontend && bun dev         # UI :3000
```

Env: `frontend/.env` → `NEXT_PUBLIC_API_URL=http://localhost:8000`

## Skill: Adding Final Sheet product/volumes (future)

1. Restore `Mozambique_Report_24 Feb/6_Process/*.xlsx` or `RAW SHEET.csv` under `backend/data/`.
2. Point `SurveySpec.volumes_rel` in `catalog.py`.
3. `load_volumes()` already parses Name / Pile Name / Net Volume / Product.
4. Merge into piles; keep morphometric classification as fallback.
