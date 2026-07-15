"""Compute stockpile volumes / morphometrics from DEM + pile polygons."""

from __future__ import annotations

from typing import Any

import numpy as np

from app.services.patio_classify import geom_rings
from app.services.volumes import normalize_pile_id, parse_number, patio_from_pile_id


def _detect_src_crs(geojson: dict[str, Any], default: str = "EPSG:32737") -> str:
    crs = geojson.get("crs") or {}
    props = crs.get("properties") or {}
    name = props.get("name")
    if isinstance(name, str) and "EPSG" in name.upper():
        # e.g. urn:ogc:def:crs:EPSG::32737
        token = name.split(":")[-1]
        if token.isdigit():
            return f"EPSG:{token}"
    return default


def _warp_ring(ring: list[list[float]], src_crs: str, dst_crs: str) -> list[list[float]]:
    if src_crs == dst_crs:
        return ring
    from rasterio.warp import transform as warp_transform

    xs, ys = warp_transform(src_crs, dst_crs, [p[0] for p in ring], [p[1] for p in ring])
    return [[x, y] for x, y in zip(xs, ys, strict=False)]


def compute_pile_metrics_from_dem(
    dem_path,
    geojson: dict[str, Any],
    *,
    pile_crs: str | None = None,
) -> list[dict[str, Any]]:
    """
    For each named NC_* polygon, compute net volume above a local base plane
    (5th percentile elev inside polygon), area, height, and mean slope.
    """
    import rasterio
    from rasterio import features as rio_features
    from rasterio.windows import from_bounds

    src_crs = pile_crs or _detect_src_crs(geojson)
    results: list[dict[str, Any]] = []

    with rasterio.open(dem_path) as ds:
        dem_crs = ds.crs.to_string() if ds.crs else "EPSG:21037"
        nodata = ds.nodata if ds.nodata is not None else -32767.0
        cell = abs(ds.transform.a)
        cell_area = cell * abs(ds.transform.e)

        for idx, feature in enumerate(geojson.get("features") or []):
            props = dict(feature.get("properties") or {})
            raw_name = props.get("NAME") or props.get("Name") or props.get("name")
            if not raw_name:
                continue
            name = normalize_pile_id(str(raw_name).strip())
            if not name.upper().startswith("NC_"):
                continue

            rings = geom_rings(feature.get("geometry") or {})
            if not rings:
                continue
            ring = max(rings, key=len)
            warped = _warp_ring(ring, src_crs, dem_crs)
            xs = [p[0] for p in warped]
            ys = [p[1] for p in warped]
            pad = cell * 2
            minx, miny, maxx, maxy = min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad

            try:
                window = from_bounds(minx, miny, maxx, maxy, transform=ds.transform)
                data = ds.read(1, window=window, boundless=True, fill_value=nodata).astype(np.float32)
                transform = ds.window_transform(window)
            except Exception:  # noqa: BLE001
                continue

            valid = np.isfinite(data) & (data != nodata) & (data > -1000)
            data = np.where(valid, data, np.nan)

            mask = rio_features.geometry_mask(
                [{"type": "Polygon", "coordinates": [warped]}],
                out_shape=data.shape,
                transform=transform,
                invert=True,
            )
            vals = data[mask & np.isfinite(data)]
            if vals.size < 5:
                continue

            base = float(np.nanpercentile(vals, 5))
            height = vals - base
            height = np.where(height > 0, height, 0.0)
            net_vol = float(np.nansum(height) * cell_area)
            area_m2 = float(np.count_nonzero(mask & np.isfinite(data)) * cell_area)
            min_e = float(np.nanmin(vals))
            max_e = float(np.nanmax(vals))
            avg_e = float(np.nanmean(vals))

            # mean slope degrees from DEM gradients inside mask
            filled = np.where(np.isfinite(data), data, avg_e)
            gy, gx = np.gradient(filled, cell, cell)
            slope_deg = np.degrees(np.arctan(np.hypot(gx, gy)))
            slope_vals = slope_deg[mask & np.isfinite(data)]
            avg_slope = float(np.nanmean(slope_vals)) if slope_vals.size else None

            # Prefer attribute elev/slope when present
            attr_min = parse_number(props.get("MIN_ELEV_M"))
            attr_max = parse_number(props.get("MAX_ELEV_M"))
            attr_slope = parse_number(props.get("AVG_SLOPE_") or props.get("AVG_SLOPE"))
            attr_area = parse_number(props.get("area_ha") or props.get("ENCLOSED_A"))

            # Centroid in original pile CRS (figures warp 32737→DEM themselves)
            ox = [p[0] for p in ring]
            oy = [p[1] for p in ring]

            results.append(
                {
                    "id": name,
                    "name": name,
                    "patio": patio_from_pile_id(name),
                    "net_volume_m3": net_vol,
                    "total_volume_m3": net_vol,
                    "enclosed_area_ha": attr_area if attr_area is not None else area_m2 / 10_000.0,
                    "min_elev_m": attr_min if attr_min is not None else min_e,
                    "max_elev_m": attr_max if attr_max is not None else max_e,
                    "avg_elev_m": avg_e,
                    "centroid": [sum(ox) / len(ox), sum(oy) / len(oy)],
                    "geometry": feature.get("geometry"),
                    "properties": {
                        **props,
                        "AVG_SLOPE_": attr_slope if attr_slope is not None else avg_slope,
                        "NAME": name,
                        "volume_source": "dem_cut_above_p5_base",
                        "pile_crs": src_crs,
                    },
                }
            )

    return results
