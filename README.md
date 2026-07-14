# AIMS RDR — DEM & Ortho Survey Monitoring

Enterprise monitoring for inspection-date surveys using **DEM + Ortho** as the source of truth.

**Inputs per inspection**
- **DEM:** `.tif` + `.tfw` + `.prj`
- **Ortho:** `.ecw` + `.eww` + `.prj` (GeoTIFF ortho also supported)

**Outputs (backend → JSON + optimized previews)**
- DEM metadata, elevation-colored preview, hillshade, heightmap (for 3D)
- Ortho preview (when GDAL can decode ECW / GeoTIFF)
- DEM of Difference (DoD) change map between two dates
- Optional vector overlays (piles/patio) when present

Next.js never loads raw multi-GB rasters. Dockerized GDAL builds browser-ready products.

---

## Architecture

```text
DEM (TIF/TFW/PRJ) + Ortho (ECW/EWW/PRJ)
            │
            ▼
   FastAPI + GDAL (Docker)
     • gdal_translate downsample
     • dem preview / heightmap / hillshade
     • ortho preview
     • DoD (to − from)
            │
            ▼
   processed/*.png|jpg|json  +  site/survey JSON
            │
            ▼
   Next.js monitoring UI
     • Inspect by date
     • Compare by dates
     • 3D DEM terrain
     • Ortho + DoD panels
```

---

## Run

### Backend (Docker — required for DEM/Ortho processing)

```bash
docker compose up --build
```

First process of large DEMs can take several minutes. Trigger again from the UI (**Process DEM/Ortho**) or:

```bash
curl -X POST http://localhost:8000/api/v1/sites/nacala-coal-field/process
```

API docs: http://localhost:8000/docs  
Capabilities: http://localhost:8000/api/v1/capabilities  

### Frontend

```bash
cd frontend
npm install   # or bun install
npm run dev   # or bun dev
```

Set `NEXT_PUBLIC_API_URL=http://localhost:8000`.

---

## UI routes

| Route | Content |
|-------|---------|
| `/monitor` | Dashboard overview + quick links |
| `/monitor/3d` | True-color 3D point cloud |
| `/monitor/dem` | DEM / GeoTIFF viewer |
| `/monitor/change` | DoD change heatmap |
| `/monitor/ortho` | Ortho RGB imagery |
| `/monitor/parameters` | Parameters + pothole/rut/heave defect candidates |

Modes: **Inspect date** (single survey) · **Compare dates** (DoD + defects, default 24 Feb → 3 Mar).

---

## Data layout (current seed)

Place each inspection under `backend/data/<date>/`:

```text
backend/data/
  24 February/
    dem/   Nacala-Port & Coal-Field Stage-4-1.tif + .tfw + .prj
    ortho/ MOZAMBIQUE PORT & COAL FIELD 24-Feb.ecw + .eww + .prj
  3rd March/
    dem/   Nacala-Port & Coal-Field Stage-6.tif + .tfw + .prj
    ortho/ MOZAMBIQUE PORT & COAL FIELD 03-March.ecw + .eww + .prj
```

**Notes**
- **ECW → RGB:** Docker GDAL cannot read ECW. On Windows with QGIS installed, run:
  `powershell -File scripts/convert_ortho_ecw.ps1`
  then **Process DEM/Ortho** (or restart API). That writes true-color `{survey}-ortho-rgb.tif` used for 3D + viewer — same imagery as QGIS.
- **CRS:** Deliveries may mix Arc 1960 / UTM 37S (DEM) with WGS84 / UTM 37S (ortho/other DEM). DoD always reprojects onto the “from” DEM grid before differencing.

---

## API (high level)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/sites/{id}` | Site + surveys + raster product URLs |
| `GET /api/v1/sites/{id}/compare?from=&to=` | Comparison + DoD |
| `POST /api/v1/sites/{id}/process` | Rebuild DEM/Ortho/DoD products |
| `GET /api/v1/media/{id}/{file}` | Previews (png/jpg) + JSON/GeoJSON |

---

## Optimization choices

- Downsampled DEM products (`~1024–1536 px`) for UI speed
- Heightmap displacement in the browser (not raw TIF)
- DoD on aligned downsampled grids
- Skip reprocessing on container restart if primary DEM preview already exists
- Raw `backend/data/` stays gitignored and mounted read-only in Docker

---

## Roadmap

- Full XYZ/COG tile pyramid for deep zoom
- Cross-section profiles from DEM
- True volumetric cut/fill from DoD × pixel area
- LAS/LiDAR + AI prediction layer
- GeoTIFF ortho ingest as default imagery path
