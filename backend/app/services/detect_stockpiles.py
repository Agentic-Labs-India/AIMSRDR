"""Detect coal stockpile polygons from DEM only (no shapefile required)."""

from __future__ import annotations

from typing import Any

import numpy as np


def detect_stockpiles_from_dem(
    dem_path,
    *,
    max_dim: int = 1024,
    height_m: float = 0.8,
    min_area_m2: float = 120.0,
    max_piles: int = 40,
) -> dict[str, Any]:
    """
    Return GeoJSON FeatureCollection of detected stockpiles named NC_CY{A|B|C}_P_##.
    Geometries are in the DEM CRS (set pile_crs on each feature).
    """
    import rasterio
    from rasterio import features as rio_features
    from rasterio.enums import Resampling
    from rasterio.transform import Affine, xy
    from scipy import ndimage

    with rasterio.open(dem_path) as ds:
        dem_crs = ds.crs.to_string() if ds.crs else "EPSG:21037"
        nodata = ds.nodata if ds.nodata is not None else -32767.0
        scale = max(ds.width / max_dim, ds.height / max_dim, 1.0)
        out_w = max(32, int(ds.width / scale))
        out_h = max(32, int(ds.height / scale))
        elev = ds.read(
            1,
            out_shape=(out_h, out_w),
            resampling=Resampling.average,
        ).astype(np.float32)
        transform = ds.transform * Affine.scale(ds.width / out_w, ds.height / out_h)
        cell_x = abs(transform.a)
        cell_y = abs(transform.e)
        cell_area = cell_x * cell_y

    valid = np.isfinite(elev) & (elev != nodata) & (elev > -1000)
    elev = np.where(valid, elev, np.nan)
    if np.count_nonzero(valid) < 500:
        raise ValueError("DEM has too few valid elevation samples for stockpile detection")

    fill = float(np.nanpercentile(elev[valid], 10))
    elev_f = np.where(valid, elev, fill)

    # Cap kernel — uncapped size on cm-GSD DEMs was hanging the API for minutes.
    open_px = int(round(30.0 / max(cell_x, 0.2)))
    open_px = int(np.clip(open_px, 5, 21))
    if open_px % 2 == 0:
        open_px += 1

    ground = ndimage.grey_opening(elev_f, size=(open_px, open_px))
    ndsm = np.where(valid, elev_f - ground, 0.0)

    mask = valid & (ndsm >= height_m)
    mask = ndimage.binary_opening(mask, iterations=1)
    mask = ndimage.binary_closing(mask, iterations=1)

    labels, nlab = ndimage.label(mask)
    if nlab == 0:
        raise ValueError(
            "No stockpile mounds detected above the patio floor. "
            "Check DEM sidecars (.tfw/.prj) with the .tif."
        )

    comps: list[dict[str, Any]] = []
    for lab in range(1, nlab + 1):
        m = labels == lab
        area = float(np.count_nonzero(m) * cell_area)
        if area < min_area_m2:
            continue
        ys, xs = np.where(m)
        east, north = xy(transform, float(ys.mean()), float(xs.mean()), offset="center")
        comps.append(
            {
                "label": lab,
                "area_m2": area,
                "east": float(east),
                "north": float(north),
                "peak_m": float(np.nanmax(ndsm[m])),
                "mask": m,
            }
        )

    if not comps:
        raise ValueError(f"Detected blobs were smaller than min area ({min_area_m2} m²)")

    comps.sort(key=lambda c: c["area_m2"], reverse=True)
    comps = comps[:max_piles]

    pts = np.array([[c["east"], c["north"]] for c in comps], dtype=float)
    mean = pts.mean(axis=0)
    centered = pts - mean
    cov = np.cov(centered.T) if len(comps) > 1 else np.eye(2)
    eigvals, eigvecs = np.linalg.eigh(cov)
    long_axis = eigvecs[:, int(np.argmax(eigvals))]
    cross_axis = np.array([-long_axis[1], long_axis[0]])
    chain = centered @ long_axis
    cross = centered @ cross_axis

    qs = np.quantile(cross, [0.33, 0.66]) if len(cross) >= 6 else None
    for i, c in enumerate(comps):
        c["chain"] = float(chain[i])
        if qs is None:
            c["patio"] = "A"
        elif cross[i] <= qs[0]:
            c["patio"] = "A"
        elif cross[i] <= qs[1]:
            c["patio"] = "B"
        else:
            c["patio"] = "C"

    by_patio: dict[str, list[dict[str, Any]]] = {"A": [], "B": [], "C": []}
    for c in comps:
        by_patio.setdefault(c["patio"], []).append(c)
    for patio, items in by_patio.items():
        items.sort(key=lambda c: c["chain"])
        for idx, c in enumerate(items, start=1):
            c["name"] = f"NC_CY{patio}_P_{idx:02d}"

    features: list[dict[str, Any]] = []
    for c in comps:
        shapes = list(
            rio_features.shapes(
                c["mask"].astype(np.uint8),
                mask=c["mask"],
                transform=transform,
            )
        )
        if not shapes:
            continue
        geom, _val = max(shapes, key=lambda s: _poly_area(s[0]))
        if geom["type"] == "Polygon":
            geometry = geom
        elif geom["type"] == "MultiPolygon":
            best = max(geom["coordinates"], key=lambda poly: abs(_ring_area(poly[0])))
            geometry = {"type": "Polygon", "coordinates": best}
        else:
            continue

        features.append(
            {
                "type": "Feature",
                "properties": {
                    "NAME": c["name"],
                    "feature_id": c["name"],
                    "patio": c["patio"],
                    "area_m2": c["area_m2"],
                    "area_ha": c["area_m2"] / 10_000.0,
                    "peak_height_m": c["peak_m"],
                    "detection": "dem_ndsm",
                    "pile_crs": dem_crs,
                    "centroid_x": c["east"],
                    "centroid_y": c["north"],
                },
                "geometry": geometry,
            }
        )

    features.sort(key=lambda f: f["properties"]["NAME"])
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": dem_crs}},
        "features": features,
        "meta": {
            "dem_crs": dem_crs,
            "cell_m": [cell_x, cell_y],
            "height_threshold_m": height_m,
            "min_area_m2": min_area_m2,
            "pile_count": len(features),
            "open_px": open_px,
        },
    }


def _ring_area(ring: list) -> float:
    if len(ring) < 3:
        return 0.0
    area = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[i + 1][0], ring[i + 1][1]
        area += x1 * y2 - x2 * y1
    return area * 0.5


def _poly_area(geom: dict[str, Any]) -> float:
    if geom.get("type") == "Polygon":
        return abs(_ring_area(geom["coordinates"][0]))
    if geom.get("type") == "MultiPolygon":
        return sum(abs(_ring_area(p[0])) for p in geom["coordinates"])
    return 0.0
