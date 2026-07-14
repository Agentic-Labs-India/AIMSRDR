from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None


def gdal_available() -> bool:
    return shutil.which("gdalinfo") is not None and shutil.which("gdal_translate") is not None


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def parse_tfw(tfw_path: Path) -> dict[str, float] | None:
    if not tfw_path.exists():
        return None
    vals = [float(line.strip()) for line in tfw_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(vals) < 6:
        return None
    return {
        "pixel_size_x": vals[0],
        "rotation_y": vals[1],
        "rotation_x": vals[2],
        "pixel_size_y": vals[3],
        "origin_x": vals[4],
        "origin_y": vals[5],
    }


def parse_prj(prj_path: Path) -> str | None:
    if not prj_path.exists():
        return None
    return prj_path.read_text(encoding="utf-8", errors="ignore").strip() or None


def gdalinfo_json(path: Path) -> dict[str, Any]:
    result = _run(["gdalinfo", "-json", str(path)])
    return json.loads(result.stdout)


def extract_raster_metadata(path: Path) -> dict[str, Any]:
    """DEM/Ortho metadata from GDAL + sidecar TFW/PRJ/EWW."""
    info = gdalinfo_json(path)
    size = info.get("size") or [None, None]
    bands = info.get("bands") or []
    corner = info.get("cornerCoordinates") or {}
    geo = info.get("geoTransform") or []
    srs = (info.get("coordinateSystem") or {}).get("wkt") or ""
    epsg = None
    if "AUTHORITY[\"EPSG\"" in srs:
        try:
            epsg = int(srs.split('AUTHORITY["EPSG","')[-1].split('"]')[0])
        except Exception:  # noqa: BLE001
            epsg = None

    pixel_x = abs(float(geo[1])) if len(geo) >= 6 else None
    pixel_y = abs(float(geo[5])) if len(geo) >= 6 else None
    tfw = parse_tfw(path.with_suffix(".tfw")) or parse_tfw(path.with_suffix(".eww"))
    if tfw and pixel_x is None:
        pixel_x = abs(tfw["pixel_size_x"])
        pixel_y = abs(tfw["pixel_size_y"])

    band0 = bands[0] if bands else {}
    stats = None
    if "computedStatistics" in band0:
        stats = band0["computedStatistics"]
    elif "metadata" in band0:
        # sometimes STATISTICS_* live here
        meta = band0.get("metadata", {})
        default = meta.get("") if isinstance(meta, dict) else {}
        if isinstance(default, dict) and "STATISTICS_MINIMUM" in default:
            stats = {
                "minimum": float(default["STATISTICS_MINIMUM"]),
                "maximum": float(default["STATISTICS_MAXIMUM"]),
                "mean": float(default.get("STATISTICS_MEAN", 0)),
                "stdDev": float(default.get("STATISTICS_STDDEV", 0)),
            }

    width, height = size[0], size[1]
    area_km2 = None
    if width and height and pixel_x and pixel_y:
        area_km2 = (width * pixel_x * height * pixel_y) / 1_000_000.0

    ul = corner.get("upperLeft")
    lr = corner.get("lowerRight")
    extent = None
    if ul and lr:
        extent = {
            "min_x": float(ul[0]),
            "max_y": float(ul[1]),
            "max_x": float(lr[0]),
            "min_y": float(lr[1]),
        }

    return {
        "path": str(path.name),
        "driver": (info.get("driverShortName") or path.suffix.lstrip(".")).upper(),
        "width_px": width,
        "height_px": height,
        "band_count": len(bands),
        "dtype": band0.get("type"),
        "crs_epsg": epsg,
        "crs_wkt": srs[:500] if srs else parse_prj(path.with_suffix(".prj")),
        "pixel_size_m": [pixel_x, pixel_y],
        "gsd_cm": round(pixel_x * 100, 2) if pixel_x else None,
        "extent": extent,
        "bbox_corners": corner,
        "elevation_stats": stats,
        "area_km2": round(area_km2, 4) if area_km2 is not None else None,
        "file_bytes": path.stat().st_size if path.exists() else None,
        "sidecars": {
            "tfw": path.with_suffix(".tfw").exists() or path.with_suffix(".eww").exists(),
            "prj": path.with_suffix(".prj").exists(),
        },
    }


def _source_nodata(path: Path) -> float | None:
    try:
        info = gdalinfo_json(path)
        bands = info.get("bands") or []
        if bands and bands[0].get("noDataValue") is not None:
            return float(bands[0]["noDataValue"])
    except Exception:  # noqa: BLE001
        pass
    return None


def _downsample_path(src: Path, dst: Path, max_dim: int = 1536) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "gdal_translate",
        "-of",
        "GTiff",
        "-co",
        "COMPRESS=LZW",
        "-outsize",
        str(max_dim),
        "0",
        str(src),
        str(dst),
    ]
    nodata = _source_nodata(src)
    if nodata is not None:
        # Keep nodata explicit so resampling does not invent elevations.
        cmd[1:1] = ["-a_nodata", str(nodata)]
    _run(cmd)
    return dst


def _mask_invalid_elevations(arr: np.ndarray, nodata: float | None = None) -> np.ndarray:
    """Treat nodata / extreme sentinels as NaN so DoD/stats stay sane."""
    out = arr.astype(np.float32, copy=True)
    out[~np.isfinite(out)] = np.nan
    if nodata is not None and np.isfinite(nodata):
        out[np.isclose(out, nodata, atol=0.5)] = np.nan
    # Common float DEM sentinels and absurd values for stockyard surveys
    out[out <= -1000] = np.nan
    out[out >= 9000] = np.nan
    return out


def _read_band(path: Path, *, mask_elevations: bool = True) -> tuple[np.ndarray, dict[str, Any]]:
    import rasterio

    with rasterio.open(path) as ds:
        data = ds.read(1)
        meta = {
            "transform": ds.transform,
            "crs": ds.crs.to_string() if ds.crs else None,
            "width": ds.width,
            "height": ds.height,
            "nodata": ds.nodata,
            "res": ds.res,
        }
        arr = np.array(data, dtype=np.float32, copy=True)
        if ds.nodata is not None and np.isfinite(ds.nodata):
            arr[np.isclose(arr, float(ds.nodata), atol=0.5)] = np.nan
        if mask_elevations:
            arr = _mask_invalid_elevations(arr, ds.nodata)
        else:
            arr[~np.isfinite(arr)] = np.nan
        return arr, meta


def _normalize_uint8(arr: np.ndarray, p_low: float = 2, p_high: float = 98) -> np.ndarray:
    data = np.asarray(arr, dtype=np.float32)
    valid = data[np.isfinite(data)]
    if valid.size == 0:
        return np.zeros(data.shape, dtype=np.uint8)
    lo, hi = np.percentile(valid, [p_low, p_high])
    if math.isclose(float(lo), float(hi)):
        hi = lo + 1.0
    scaled = (data - lo) / (hi - lo)
    scaled = np.clip(scaled, 0, 1)
    scaled = np.where(np.isfinite(data), scaled, 0.0)
    return np.nan_to_num(scaled * 255.0, nan=0.0, posinf=255.0, neginf=0.0).astype(np.uint8)


def _elevation_color(arr: np.ndarray) -> np.ndarray:
    """Terrain RGB ramp: deep blue → teal → green → yellow → red."""
    gray = _normalize_uint8(arr)
    x = gray.astype(np.float32) / 255.0
    r = np.clip(1.55 * x - 0.15, 0, 1)
    g = np.clip(1.25 - abs(x - 0.42) * 2.1, 0, 1)
    b = np.clip(1.15 - x * 1.35, 0, 1)
    rgb = np.dstack([r, g, b])
    rgb = (rgb * 255).astype(np.uint8)
    mask = ~np.isfinite(arr)
    rgb[mask] = (15, 23, 42)
    return rgb


def _blend_rgb_hillshade(rgb: np.ndarray, hillshade: np.ndarray) -> np.ndarray:
    """Multiply elevation RGB by hillshade for a natural-looking RGB surface."""
    hs = np.asarray(hillshade, dtype=np.float32)
    if hs.ndim == 3:
        hs = hs[:, :, 0]
    hs = np.nan_to_num(hs, nan=0.0) / 255.0
    # Keep shadows readable (lift floor a bit).
    hs = 0.35 + 0.65 * hs
    out = np.asarray(rgb, dtype=np.float32) * hs[:, :, None]
    return np.clip(np.nan_to_num(out, nan=0.0), 0, 255).astype(np.uint8)


def _write_rgb_geotiff(src_dem: Path, rgb: np.ndarray, dst: Path) -> None:
    """Write a 3-band Byte RGB GeoTIFF georeferenced like the source DEM."""
    import rasterio
    from rasterio.enums import ColorInterp

    dst.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(src_dem) as src:
        profile = src.profile.copy()
        profile.update(
            driver="GTiff",
            count=3,
            dtype="uint8",
            nodata=None,
            compress="lzw",
            photometric="RGB",
        )
        with rasterio.open(dst, "w", **profile) as out:
            # rgb is H×W×3
            out.write(np.transpose(rgb, (2, 0, 1)))
            out.colorinterp = [ColorInterp.red, ColorInterp.green, ColorInterp.blue]


def _dod_color(delta: np.ndarray, limit: float = 0.5) -> np.ndarray:
    """Blue (cut/loss) → white → red (fill/gain), clipped to ±limit meters."""
    safe_limit = limit if limit and limit > 0 else 0.5
    finite = np.isfinite(delta)
    t = np.zeros(delta.shape, dtype=np.float32)
    t[finite] = np.clip(delta[finite] / safe_limit, -1.0, 1.0)
    r = np.where(t > 0, 0.55 + 0.45 * t, 0.55 + 0.45 * t)
    g = np.where(np.abs(t) < 0.15, 0.9, 0.35 + 0.4 * (1.0 - np.abs(t)))
    b = np.where(t < 0, 0.55 + 0.45 * (-t), 0.35 + 0.2 * (1.0 - t))
    rgb = (np.clip(np.dstack([r, g, b]), 0, 1) * 255).astype(np.uint8)
    rgb[~finite] = (15, 23, 42)
    return rgb


def process_dem(dem_path: Path, out_dir: Path, survey_id: str, max_dim: int = 1536) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = extract_raster_metadata(dem_path)
    scaled = out_dir / f"{survey_id}-dem-scaled.tif"
    preview = out_dir / f"{survey_id}-dem-preview.png"
    rgb_png = out_dir / f"{survey_id}-dem-rgb.png"
    rgb_tif = out_dir / f"{survey_id}-dem-rgb.tif"
    heightmap = out_dir / f"{survey_id}-dem-heightmap.png"
    hillshade = out_dir / f"{survey_id}-dem-hillshade.png"

    _downsample_path(dem_path, scaled, max_dim=max_dim)
    arr, _ = _read_band(scaled)

    # Prefer stats from masked preview grid (nodata already removed).
    valid = arr[np.isfinite(arr)]
    if valid.size:
        meta["elevation_stats"] = {
            "minimum": float(np.min(valid)),
            "maximum": float(np.max(valid)),
            "mean": float(np.mean(valid)),
            "stdDev": float(np.std(valid)),
        }
        meta["valid_pixel_share"] = float(valid.size / arr.size)

    elev_rgb = _elevation_color(arr)
    Image.fromarray(_normalize_uint8(arr), mode="L").save(heightmap, optimize=True)

    # Hillshade via gdaldem when available
    hs_u8: np.ndarray
    try:
        hs_tif = out_dir / f"{survey_id}-dem-hillshade.tif"
        _run(["gdaldem", "hillshade", "-z", "1.5", str(scaled), str(hs_tif)])
        hs_arr, _ = _read_band(hs_tif, mask_elevations=False)
        hs_u8 = _normalize_uint8(hs_arr, 0, 100)
        Image.fromarray(np.ascontiguousarray(hs_u8), mode="L").save(hillshade, optimize=True)
        hs_tif.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        hs_u8 = _normalize_uint8(arr)
        Image.fromarray(np.ascontiguousarray(hs_u8), mode="L").save(hillshade, optimize=True)

    # RGB = elevation color × hillshade (true 3-band product for UI + GIS)
    rgb = _blend_rgb_hillshade(elev_rgb, hs_u8)
    Image.fromarray(elev_rgb, mode="RGB").save(preview, optimize=True)
    Image.fromarray(rgb, mode="RGB").save(rgb_png, optimize=True)
    _write_rgb_geotiff(scaled, rgb, rgb_tif)

    meta_path = out_dir / f"{survey_id}-dem-meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return {
        "metadata": meta,
        "preview_url": f"/api/v1/media/{out_dir.name}/{preview.name}" if False else preview.name,
        "files": {
            "meta": meta_path.name,
            "preview": preview.name,
            "rgb": rgb_png.name,
            "rgb_tif": rgb_tif.name,
            "heightmap": heightmap.name,
            "hillshade": hillshade.name,
            "scaled": scaled.name,
        },
    }


def _ortho_sidecar_metadata(ortho_path: Path) -> dict[str, Any]:
    """Best-effort metadata when the ECW driver is unavailable."""
    eww = parse_tfw(ortho_path.with_suffix(".eww")) or parse_tfw(ortho_path.with_suffix(".tfw"))
    prj = parse_prj(ortho_path.with_suffix(".prj"))
    meta: dict[str, Any] = {
        "path": ortho_path.name,
        "driver": ortho_path.suffix.lstrip(".").upper(),
        "file_bytes": ortho_path.stat().st_size if ortho_path.exists() else None,
        "crs_wkt": prj,
        "crs_epsg": (
            32737
            if prj and "WGS" in prj.upper() and "37" in prj
            else 21037
            if prj and ("ARC" in prj.upper() or "1960" in prj) and "37" in prj
            else 32737
            if prj and "UTM" in prj.upper() and "37" in prj
            else None
        ),
        "sidecars": {
            "tfw": (ortho_path.with_suffix(".eww").exists() or ortho_path.with_suffix(".tfw").exists()),
            "prj": ortho_path.with_suffix(".prj").exists(),
        },
        "world_file": eww,
    }
    if eww:
        meta["pixel_size_m"] = [abs(eww["pixel_size_x"]), abs(eww["pixel_size_y"])]
        meta["gsd_cm"] = round(abs(eww["pixel_size_x"]) * 100, 2)
        meta["origin"] = [eww["origin_x"], eww["origin_y"]]
    return meta


def resolve_ortho_source(
    data_root: Path,
    ortho_rel: Path | None,
    out_dir: Path,
    survey_id: str,
) -> Path | None:
    """Prefer GeoTIFF ortho; fall back to cached RGB convert, then ECW."""
    if ortho_rel is None:
        cached = out_dir / f"{survey_id}-ortho-rgb.tif"
        return cached if cached.exists() else None

    primary = data_root / ortho_rel
    candidates = [
        primary.with_suffix(".tif"),
        primary.with_suffix(".tiff"),
        primary.with_name(f"{primary.stem}_rgb.tif"),
        primary.with_name(f"{primary.stem}_preview.tif"),
        out_dir / f"{survey_id}-ortho-rgb.tif",
        primary,
    ]
    for path in candidates:
        if path.exists() and path.is_file() and path.stat().st_size > 0:
            return path
    return None


def process_ortho(ortho_path: Path, out_dir: Path, survey_id: str, max_dim: int = 1536) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "status": "pending",
        "metadata": None,
        "files": {},
        "note": None,
    }

    sources = [ortho_path]
    cached_rgb = out_dir / f"{survey_id}-ortho-rgb.tif"
    if cached_rgb.exists() and cached_rgb.resolve() != ortho_path.resolve():
        sources.append(cached_rgb)

    last_error: Exception | None = None
    for source in sources:
        try:
            meta = extract_raster_metadata(source)
            result["metadata"] = meta
            scaled = out_dir / f"{survey_id}-ortho-scaled.tif"
            preview = out_dir / f"{survey_id}-ortho-preview.jpg"
            # Keep only RGB for multi-band orthos (ECW often has alpha as band 4).
            _run(
                [
                    "gdal_translate",
                    "-b",
                    "1",
                    "-b",
                    "2",
                    "-b",
                    "3",
                    "-of",
                    "GTiff",
                    "-co",
                    "COMPRESS=LZW",
                    "-outsize",
                    str(max_dim),
                    "0",
                    str(source),
                    str(scaled),
                ]
            )

            import rasterio

            with rasterio.open(scaled) as ds:
                count = min(ds.count, 3)
                if count >= 3:
                    data = ds.read([1, 2, 3])
                    rgb = np.transpose(data, (1, 2, 0))
                else:
                    band = ds.read(1)
                    rgb = np.dstack([band, band, band])
                out = np.zeros(rgb.shape, dtype=np.uint8)
                for i in range(rgb.shape[2]):
                    out[:, :, i] = _normalize_uint8(rgb[:, :, i].astype(np.float32))
                Image.fromarray(out, mode="RGB").save(preview, quality=88, optimize=True)

            meta_path = out_dir / f"{survey_id}-ortho-meta.json"
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            result["status"] = "processed"
            result["note"] = (
                "True-color RGB ortho ready for 3D / viewer."
                if source.suffix.lower() in {".tif", ".tiff"}
                else "Ortho preview generated."
            )
            result["files"] = {
                "meta": meta_path.name,
                "preview": preview.name,
                "scaled": scaled.name,
                "rgb_tif": source.name if source.name.endswith("-ortho-rgb.tif") else None,
            }
            result["files"] = {k: v for k, v in result["files"].items() if v}
            return result
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue

    sidecar_meta = _ortho_sidecar_metadata(ortho_path)
    meta_path = out_dir / f"{survey_id}-ortho-meta.json"
    meta_path.write_text(json.dumps(sidecar_meta, indent=2), encoding="utf-8")
    result["metadata"] = sidecar_meta
    result["files"] = {"meta": meta_path.name}
    result["status"] = "unavailable"
    result["note"] = (
        f"Ortho could not be decoded ({last_error}). "
        "Docker GDAL has no ECW driver. Convert ECW→GeoTIFF with QGIS "
        "(scripts/convert_ortho_ecw.ps1) or place a .tif beside the ECW."
    )
    return result


def _crs_wkt_or_proj(path: Path) -> str | None:
    info = gdalinfo_json(path)
    wkt = (info.get("coordinateSystem") or {}).get("wkt")
    if wkt:
        return wkt
    # Fall back to sidecar PRJ
    return parse_prj(path.with_suffix(".prj"))


def process_dod(
    dem_a: Path,
    dem_b: Path,
    out_dir: Path,
    pair_id: str,
    max_dim: int = 1280,
    limit_m: float | None = None,
) -> dict[str, Any]:
    """DEM of Difference: B - A (to - from), reprojected onto A's grid."""
    out_dir.mkdir(parents=True, exist_ok=True)
    a_scaled = out_dir / f"{pair_id}-a.tif"
    b_scaled = out_dir / f"{pair_id}-b.tif"
    _downsample_path(dem_a, a_scaled, max_dim=max_dim)

    nodata_a = _source_nodata(dem_a)
    nodata_b = _source_nodata(dem_b)
    px, py = _pixel_size(a_scaled)
    target_srs = _crs_wkt_or_proj(a_scaled) or _crs_wkt_or_proj(dem_a)

    # Reproject B onto A's CRS + exact grid. Required when deliveries mix
    # Arc 1960 / UTM 37S with WGS84 / UTM 37S (same zone, different datum).
    warp_cmd = [
        "gdalwarp",
        "-overwrite",
        "-r",
        "bilinear",
        "-of",
        "GTiff",
        "-co",
        "COMPRESS=LZW",
        "-tr",
        str(px),
        str(py),
        "-te",
        *_extent_args(a_scaled),
    ]
    if target_srs:
        warp_cmd.extend(["-t_srs", target_srs])
    if nodata_b is not None:
        warp_cmd.extend(["-srcnodata", str(nodata_b)])
    if nodata_a is not None:
        warp_cmd.extend(["-dstnodata", str(nodata_a)])
    warp_cmd.extend([str(dem_b), str(b_scaled)])
    _run(warp_cmd)

    a, a_meta = _read_band(a_scaled)
    b, _ = _read_band(b_scaled)
    if b.shape != a.shape:
        h, w = a.shape
        b2 = np.full_like(a, np.nan)
        hh, ww = min(h, b.shape[0]), min(w, b.shape[1])
        b2[:hh, :ww] = b[:hh, :ww]
        b = b2

    delta = b - a
    valid = delta[np.isfinite(delta)]
    if valid.size:
        p2, p98 = np.percentile(np.abs(valid), [2, 98])
        auto_limit = float(max(0.25, min(5.0, p98 if p98 > 0 else 0.5)))
    else:
        auto_limit = 0.5
    viz_limit = float(limit_m) if limit_m is not None else auto_limit

    res = a_meta.get("res") or (px, py)
    pixel_area = abs(float(res[0]) * float(res[1]))
    cut_mask = valid < -0.05
    fill_mask = valid > 0.05
    cut_m3 = float(np.abs(valid[cut_mask]).sum() * pixel_area) if valid.size else None
    fill_m3 = float(valid[fill_mask].sum() * pixel_area) if valid.size else None

    defects = _extract_surface_defects(
        delta,
        transform=a_meta.get("transform"),
        pixel_area_m2=pixel_area,
        res_xy=(float(res[0]), float(res[1])),
    )

    stats = {
        "min_m": float(np.min(valid)) if valid.size else None,
        "max_m": float(np.max(valid)) if valid.size else None,
        "mean_m": float(np.mean(valid)) if valid.size else None,
        "std_m": float(np.std(valid)) if valid.size else None,
        "abs_mean_m": float(np.mean(np.abs(valid))) if valid.size else None,
        "p2_m": float(np.percentile(valid, 2)) if valid.size else None,
        "p98_m": float(np.percentile(valid, 98)) if valid.size else None,
        "cut_share": float(np.mean(cut_mask)) if valid.size else None,
        "fill_share": float(np.mean(fill_mask)) if valid.size else None,
        "cut_volume_m3_approx": cut_m3,
        "fill_volume_m3_approx": fill_m3,
        "net_volume_m3_approx": (fill_m3 - cut_m3) if cut_m3 is not None and fill_m3 is not None else None,
        "sample_pixels": int(valid.size),
        "pixel_area_m2": pixel_area,
        "limit_m": viz_limit,
        "pothole_candidates": defects["summary"]["pothole_candidates"],
        "heave_candidates": defects["summary"]["heave_candidates"],
        "rut_candidates": defects["summary"]["rut_candidates"],
        "max_pothole_depth_m": defects["summary"]["max_pothole_depth_m"],
        "mean_pothole_depth_m": defects["summary"]["mean_pothole_depth_m"],
    }

    preview = out_dir / f"{pair_id}-dod-preview.png"
    Image.fromarray(_dod_color(delta, limit=viz_limit), mode="RGB").save(preview, optimize=True)
    stats_path = out_dir / f"{pair_id}-dod-stats.json"
    stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    defects_path = out_dir / f"{pair_id}-surface-defects.json"
    defects_path.write_text(json.dumps(defects, indent=2), encoding="utf-8")

    return {
        "stats": stats,
        "defects": defects,
        "files": {
            "preview": preview.name,
            "stats": stats_path.name,
            "defects": defects_path.name,
        },
    }


def _extract_surface_defects(
    delta: np.ndarray,
    *,
    transform: Any,
    pixel_area_m2: float,
    res_xy: tuple[float, float],
    depression_m: float = -0.08,
    heave_m: float = 0.08,
    max_features: int = 60,
) -> dict[str, Any]:
    """
    Local extrema in DoD used as surface-defect candidates.
    For roads: depressions ≈ potholes, elongated depressions ≈ ruts, positives ≈ heave/patches.
    """
    h, w = delta.shape
    step = max(3, min(h, w) // 90)
    candidates: list[dict[str, Any]] = []

    for y in range(step, h - step, step):
        for x in range(step, w - step, step):
            v = float(delta[y, x])
            if not np.isfinite(v):
                continue
            window = delta[y - step : y + step + 1, x - step : x + step + 1]
            finite = window[np.isfinite(window)]
            if finite.size < 8:
                continue

            kind = None
            severity = "low"
            if v <= depression_m and v <= float(np.min(finite)):
                # Elongation proxy: compare row vs col variance of deep cells
                deep = window <= depression_m
                ys, xs = np.where(deep)
                if ys.size >= 3 and (np.std(xs) > np.std(ys) * 1.8 or np.std(ys) > np.std(xs) * 1.8):
                    kind = "rut"
                else:
                    kind = "pothole"
                depth = abs(v)
                if depth >= 0.25:
                    severity = "critical"
                elif depth >= 0.15:
                    severity = "high"
                elif depth >= 0.10:
                    severity = "medium"
            elif v >= heave_m and v >= float(np.max(finite)):
                kind = "heave"
                depth = v
                if depth >= 0.25:
                    severity = "critical"
                elif depth >= 0.15:
                    severity = "high"
                elif depth >= 0.10:
                    severity = "medium"
            else:
                continue

            # Map pixel → projected coordinates when affine transform exists
            easting = northing = None
            try:
                if transform is not None:
                    easting, northing = transform * (x, y)
                    easting = float(easting)
                    northing = float(northing)
            except Exception:  # noqa: BLE001
                easting = northing = None

            area_m2 = float(pixel_area_m2 * max(1, int(np.sum(np.isfinite(window) & (window <= depression_m))))) if kind in {"pothole", "rut"} else float(pixel_area_m2 * step * step)
            candidates.append(
                {
                    "id": f"{kind}-{x}-{y}",
                    "type": kind,
                    "severity": severity,
                    "depth_m": round(float(depth), 3),
                    "delta_m": round(v, 3),
                    "area_m2_approx": round(area_m2, 2),
                    "pixel": [int(x), int(y)],
                    "easting": easting,
                    "northing": northing,
                }
            )

    # Keep strongest features
    candidates.sort(key=lambda d: abs(float(d["depth_m"])), reverse=True)
    top = candidates[:max_features]
    potholes = [d for d in top if d["type"] == "pothole"]
    ruts = [d for d in top if d["type"] == "rut"]
    heaves = [d for d in top if d["type"] == "heave"]
    pothole_depths = [float(d["depth_m"]) for d in potholes]

    return {
        "summary": {
            "pothole_candidates": len(potholes),
            "rut_candidates": len(ruts),
            "heave_candidates": len(heaves),
            "total_candidates": len(top),
            "max_pothole_depth_m": max(pothole_depths) if pothole_depths else None,
            "mean_pothole_depth_m": float(np.mean(pothole_depths)) if pothole_depths else None,
            "depression_threshold_m": depression_m,
            "heave_threshold_m": heave_m,
            "sample_step_px": step,
            "resolution_m": [res_xy[0], res_xy[1]],
        },
        "features": top,
    }


def _pixel_size(path: Path) -> tuple[float, float]:
    info = gdalinfo_json(path)
    gt = info.get("geoTransform") or [0, 1, 0, 0, 0, -1]
    return abs(float(gt[1])), abs(float(gt[5]))


def _extent_args(path: Path) -> list[str]:
    info = gdalinfo_json(path)
    c = info["cornerCoordinates"]
    ul, lr = c["upperLeft"], c["lowerRight"]
    # xmin ymin xmax ymax
    return [str(ul[0]), str(lr[1]), str(lr[0]), str(ul[1])]
