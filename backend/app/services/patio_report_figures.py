"""Generate MatrixGeo-style patio report figures from DEM + pile polygons.

Pile polygons are stored in EPSG:32737 (WGS 84 / UTM 37S). DEM products for
Nacala are EPSG:21037 (Arc 1960 / UTM 37S). All geometry must be warped into
the DEM CRS before windowing / sampling — otherwise profiles are empty and
plan views render as flat grey.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.services.patio_classify import geom_rings, principal_axis
from app.services.patio_report_data import PatioPileRow, PatioVolumeReport

# Delivery stockpile polygons are typically WGS84 UTM 37S (overridable per feature).
_DEFAULT_PILE_CRS = "EPSG:32737"


def _font(size: int) -> ImageFont.ImageFont:
    for name in (
        "DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _elev_to_rgb(elev: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Blue→green→yellow→red elevation ramp (MatrixGeo DEM strip look)."""
    out = np.zeros((*elev.shape, 3), dtype=np.uint8)
    if not np.any(valid):
        return out
    vals = elev[valid]
    lo = float(np.percentile(vals, 2))
    hi = float(np.percentile(vals, 98))
    if hi <= lo:
        hi = lo + 1.0
    t = np.clip((elev - lo) / (hi - lo), 0, 1)
    r = np.zeros_like(t)
    g = np.zeros_like(t)
    b = np.zeros_like(t)
    m = t <= 0.25
    u = t[m] / 0.25
    r[m] = 0
    g[m] = 180 * u
    b[m] = 220
    m = (t > 0.25) & (t <= 0.5)
    u = (t[m] - 0.25) / 0.25
    r[m] = 0
    g[m] = 180 + 75 * u
    b[m] = 220 - 220 * u
    m = (t > 0.5) & (t <= 0.75)
    u = (t[m] - 0.5) / 0.25
    r[m] = 255 * u
    g[m] = 255
    b[m] = 0
    m = t > 0.75
    u = (t[m] - 0.75) / 0.25
    r[m] = 255
    g[m] = 255 * (1 - u)
    b[m] = 0
    out[..., 0] = np.where(valid, r, 245).astype(np.uint8)
    out[..., 1] = np.where(valid, g, 245).astype(np.uint8)
    out[..., 2] = np.where(valid, b, 245).astype(np.uint8)
    return out


def _hillshade(elev: np.ndarray, cellsize: float = 1.0) -> np.ndarray:
    filled = elev.copy()
    if np.any(~np.isfinite(filled)):
        fill = float(np.nanmean(filled[np.isfinite(filled)])) if np.any(np.isfinite(filled)) else 0.0
        filled = np.where(np.isfinite(filled), filled, fill)
    dy, dx = np.gradient(filled, cellsize, cellsize)
    slope = np.pi / 2.0 - np.arctan(np.hypot(dx, dy))
    aspect = np.arctan2(-dx, dy)
    azimuth = math.radians(315.0)
    altitude = math.radians(45.0)
    shaded = np.sin(altitude) * np.sin(slope) + np.cos(altitude) * np.cos(slope) * np.cos(
        azimuth - aspect
    )
    shaded = np.clip(shaded, 0, 1)
    return (shaded * 255).astype(np.uint8)


def _dem_crs(dem_path: Path) -> str:
    import rasterio

    with rasterio.open(dem_path) as ds:
        return ds.crs.to_string() if ds.crs else "EPSG:21037"


def _warp_xy(
    xs: list[float] | np.ndarray,
    ys: list[float] | np.ndarray,
    src_crs: str,
    dst_crs: str,
) -> tuple[list[float], list[float]]:
    if src_crs == dst_crs:
        return list(xs), list(ys)
    from rasterio.warp import transform as warp_transform

    xo, yo = warp_transform(src_crs, dst_crs, list(xs), list(ys))
    return list(xo), list(yo)


def _warp_ring(ring: list[list[float]], src_crs: str, dst_crs: str) -> list[list[float]]:
    xs, ys = _warp_xy([p[0] for p in ring], [p[1] for p in ring], src_crs, dst_crs)
    return [[x, y] for x, y in zip(xs, ys, strict=False)]


def _row_rings_dem(row: PatioPileRow, dem_crs: str) -> list[list[list[float]]]:
    src = str((row.properties or {}).get("pile_crs") or _DEFAULT_PILE_CRS)
    return [_warp_ring(ring, src, dem_crs) for ring in geom_rings(row.geometry or {})]


def _bbox_of_rings(rings: list[list[list[float]]], pad: float = 8.0) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for ring in rings:
        xs.extend(p[0] for p in ring)
        ys.extend(p[1] for p in ring)
    if not xs:
        raise ValueError("No geometry for bbox")
    return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad


def _read_window(dem_path: Path, minx: float, miny: float, maxx: float, maxy: float):
    import rasterio
    from rasterio.windows import from_bounds

    with rasterio.open(dem_path) as ds:
        window = from_bounds(minx, miny, maxx, maxy, transform=ds.transform)
        # Ensure at least a few pixels
        if window.width < 2 or window.height < 2:
            raise ValueError(f"DEM window too small: {window}")
        data = ds.read(1, window=window, boundless=True, fill_value=ds.nodata or -32767).astype(
            np.float32
        )
        transform = ds.window_transform(window)
        nodata = ds.nodata if ds.nodata is not None else -32767.0
        cell = abs(ds.transform.a)
    valid = np.isfinite(data) & (data != nodata) & (data > -1000)
    data = np.where(valid, data, np.nan)
    return data, valid, transform, cell


def _sample_from_array(
    data: np.ndarray,
    transform,
    x: float,
    y: float,
) -> float | None:
    col = (x - transform.c) / transform.a
    row = (y - transform.f) / transform.e
    r = int(round(row))
    c = int(round(col))
    if r < 0 or c < 0 or r >= data.shape[0] or c >= data.shape[1]:
        return None
    val = data[r, c]
    if not np.isfinite(val):
        return None
    return float(val)


def _nice_tick_step(span: float, target_ticks: int = 10) -> float:
    """Equal tick spacing (1–2–5×10^n) covering [0, span]."""
    span = max(float(span), 1.0)
    raw = span / max(target_ticks, 2)
    magnitude = 10 ** math.floor(math.log10(raw))
    for mult in (1.0, 2.0, 5.0, 10.0):
        step = mult * magnitude
        if step >= raw:
            return step
    return magnitude * 10.0


def _affine_rotate_crop_to_strip(
    rgb: np.ndarray,
    transform,
    rings: list[list[list[float]]],
    *,
    width_px: int,
    body_h: int,
    flip_long_axis: bool = False,
) -> tuple[Image.Image, float, float, float, float, float, float, float, float, float]:
    """
    Orthorectify patio window into a horizontal strip along the pile long axis.
    Chainage increases LEFT → RIGHT (0 on the left).
    Returns (image, mx, my, vx, vy, t_min, t_max, s_min, s_max, span_t).
    """
    pts: list[list[float]] = []
    for ring in rings:
        pts.extend(ring)
    mx, my, vx, vy = principal_axis(pts)
    if flip_long_axis:
        vx, vy = -vx, -vy
    # perpendicular axis
    ux, uy = -vy, vx

    ts = [(p[0] - mx) * vx + (p[1] - my) * vy for p in pts]
    ss = [(p[0] - mx) * ux + (p[1] - my) * uy for p in pts]
    t_min, t_max = min(ts), max(ts)
    s_min, s_max = min(ss), max(ss)
    pad_s = max(2.0, (s_max - s_min) * 0.08)
    s_min -= pad_s
    s_max += pad_s
    span_t = max(t_max - t_min, 1.0)
    span_s = max(s_max - s_min, 1.0)

    # Sample: t_min at LEFT (chainage 0), t_max at RIGHT
    out = np.zeros((body_h, width_px, 3), dtype=np.uint8)
    out[:] = (245, 245, 245)
    h_src, w_src = rgb.shape[:2]

    for j in range(body_h):
        s = s_max - (j / max(body_h - 1, 1)) * span_s
        for i in range(width_px):
            t = t_min + (i / max(width_px - 1, 1)) * span_t
            x = mx + t * vx + s * ux
            y = my + t * vy + s * uy
            col = (x - transform.c) / transform.a
            row = (y - transform.f) / transform.e
            c = int(round(col))
            r = int(round(row))
            if 0 <= r < h_src and 0 <= c < w_src:
                out[j, i] = rgb[r, c]

    img = Image.fromarray(out, mode="RGB")
    return img, mx, my, vx, vy, t_min, t_max, s_min, s_max, span_t


def render_patio_dem_strip(
    dem_path: Path,
    rows: list[PatioPileRow],
    out_path: Path,
    *,
    width_px: int = 1600,
    height_px: int = 260,
) -> Path:
    """Horizontal DEM heatmap strip for ONE patio with red pile boxes + chainage ruler."""
    if not rows:
        raise ValueError("No piles for strip")

    dem_crs = _dem_crs(dem_path)
    rings_by_row: list[tuple[PatioPileRow, list[list[list[float]]]]] = []
    all_rings: list[list[list[float]]] = []
    for row in rows:
        rings = _row_rings_dem(row, dem_crs)
        if not rings:
            continue
        rings_by_row.append((row, rings))
        all_rings.extend(rings)
    if not all_rings:
        raise ValueError("No warped geometry for patio strip")

    minx, miny, maxx, maxy = _bbox_of_rings(all_rings, pad=15.0)
    data, valid, transform, _cell = _read_window(dem_path, minx, miny, maxx, maxy)
    if not np.any(valid):
        raise ValueError("DEM window has no valid elevation for patio strip")

    # Orient long axis so lower table-chainage piles sit on the LEFT (near 0)
    pts_axis = [p for _, rings in rings_by_row for ring in rings for p in ring]
    mx0, my0, vx0, vy0 = principal_axis(pts_axis)
    scored: list[tuple[float, float]] = []
    for row, rings in rings_by_row:
        rpts = [p for ring in rings for p in ring]
        cx = sum(p[0] for p in rpts) / len(rpts)
        cy = sum(p[1] for p in rpts) / len(rpts)
        t = (cx - mx0) * vx0 + (cy - my0) * vy0
        scored.append((t, float(row.chainage_start_m)))
    flip_axis = False
    if len(scored) >= 2:
        ts = np.array([s[0] for s in scored], dtype=float)
        cs = np.array([s[1] for s in scored], dtype=float)
        if np.std(ts) > 1e-6 and np.std(cs) > 1e-6:
            corr = float(np.corrcoef(ts, cs)[0, 1])
            if math.isfinite(corr) and corr < 0:
                flip_axis = True

    rgb = _elev_to_rgb(np.where(valid, data, np.nan), valid)
    body_h = height_px - 40
    strip_img, mx, my, vx, vy, t_min, _t_max, _s_min, _s_max, span_t = _affine_rotate_crop_to_strip(
        rgb,
        transform,
        all_rings,
        width_px=width_px,
        body_h=body_h,
        flip_long_axis=flip_axis,
    )

    canvas = Image.new("RGB", (width_px, height_px), (255, 255, 255))
    canvas.paste(strip_img, (0, 0))
    draw = ImageDraw.Draw(canvas)
    font = _font(12)

    # Pile boxes: geometric position on strip (0 m at LEFT)
    for _row, rings in rings_by_row:
        ts = [(p[0] - mx) * vx + (p[1] - my) * vy for ring in rings for p in ring]
        a, b = min(ts), max(ts)
        x0 = width_px * ((a - t_min) / span_t)
        x1 = width_px * ((b - t_min) / span_t)
        if x1 < x0:
            x0, x1 = x1, x0
        x0 = max(0, min(width_px - 1, x0))
        x1 = max(0, min(width_px - 1, x1))
        draw.rectangle([x0, 4, x1, body_h - 4], outline=(220, 30, 30), width=2)

    # Equidistant chainage ruler: 0 on LEFT → span on RIGHT (metres)
    max_ch = span_t
    ruler_y = height_px - 30
    draw.line([(0, ruler_y), (width_px, ruler_y)], fill=(0, 0, 0), width=1)
    step = _nice_tick_step(max_ch, target_ticks=10)
    ticks: list[float] = []
    tick = 0.0
    while tick < max_ch - step * 0.25:
        ticks.append(tick)
        tick += step
    ticks.append(max_ch)
    for ch in ticks:
        x = width_px * (ch / max_ch)
        draw.line([(x, ruler_y - 5), (x, ruler_y + 5)], fill=(0, 0, 0), width=1)
        label = str(int(round(ch)))
        # keep end labels on-canvas
        tx = max(2, min(width_px - 36, x - 10))
        draw.text((tx, ruler_y + 6), label, fill=(0, 0, 0), font=font)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, format="PNG")
    return out_path


def render_l_section_pair(
    dem_path: Path,
    row: PatioPileRow,
    out_path: Path,
    *,
    width_px: int = 1100,
    height_px: int = 420,
) -> Path:
    """L-section profile curve (left) + shaded DEM plan + boundary/centerline (right)."""
    dem_crs = _dem_crs(dem_path)
    rings = _row_rings_dem(row, dem_crs)
    if not rings:
        raise ValueError(f"No geometry for {row.pile_name}")
    ring = max(rings, key=len)
    pad = 18.0
    minx, miny, maxx, maxy = _bbox_of_rings([ring], pad=pad)
    data, valid, transform, cell = _read_window(dem_path, minx, miny, maxx, maxy)
    if not np.any(valid):
        raise ValueError(f"No DEM elevation under {row.pile_name} after CRS warp")

    mx, my, vx, vy = principal_axis(ring)
    ts = [(p[0] - mx) * vx + (p[1] - my) * vy for p in ring]
    t0, t1 = min(ts), max(ts)
    n = max(80, int((t1 - t0) / max(cell, 0.2)))
    n = min(n, 400)
    dists = np.linspace(0, max(t1 - t0, cell), n)
    profile_x: list[float] = []
    profile_z: list[float] = []
    for d in dists:
        t = t0 + float(d)
        x = mx + t * vx
        y = my + t * vy
        z = _sample_from_array(data, transform, x, y)
        if z is not None:
            profile_x.append(float(d))
            profile_z.append(z)

    # If sparse hits, bilinear-ish expand by sampling neighbors
    if len(profile_z) < 8:
        profile_x.clear()
        profile_z.clear()
        for d in dists:
            t = t0 + float(d)
            x = mx + t * vx
            y = my + t * vy
            vals = []
            for dx in (-cell, 0, cell):
                for dy in (-cell, 0, cell):
                    z = _sample_from_array(data, transform, x + dx, y + dy)
                    if z is not None:
                        vals.append(z)
            if vals:
                profile_x.append(float(d))
                profile_z.append(float(np.median(vals)))

    if len(profile_z) < 2:
        raise ValueError(f"Profile sampling failed for {row.pile_name} (CRS/DEM miss)")

    # --- Plan: hillshade under pile ---
    hs = _hillshade(data, cell)
    plan_w = width_px // 2 - 20
    plan_h = height_px - 48
    plan = Image.fromarray(np.stack([hs, hs, hs], axis=-1), mode="RGB").resize(
        (plan_w, plan_h), Image.Resampling.BILINEAR
    )
    plan_draw = ImageDraw.Draw(plan)

    def world_to_plan(x: float, y: float) -> tuple[float, float]:
        col = (x - transform.c) / transform.a
        row = (y - transform.f) / transform.e
        px = col / max(data.shape[1] - 1, 1) * (plan.width - 1)
        py = row / max(data.shape[0] - 1, 1) * (plan.height - 1)
        return px, py

    poly = [world_to_plan(p[0], p[1]) for p in ring]
    if len(poly) >= 3:
        plan_draw.line(poly + [poly[0]], fill=(220, 30, 30), width=3)
    c0 = world_to_plan(mx + t0 * vx, my + t0 * vy)
    c1 = world_to_plan(mx + t1 * vx, my + t1 * vy)
    plan_draw.line([c0, c1], fill=(220, 30, 30), width=3)
    plan_draw.polygon(
        [(c0[0] - 6, c0[1]), (c0[0] + 3, c0[1] - 5), (c0[0] + 3, c0[1] + 5)],
        fill=(220, 30, 30),
    )
    plan_draw.text((8, 8), "From", fill=(200, 20, 20), font=_font(12))

    # --- Profile graph ---
    profile = Image.new("RGB", (plan_w, plan_h), (255, 255, 255))
    pd = ImageDraw.Draw(profile)
    margin_l, margin_r, margin_t, margin_b = 48, 14, 18, 32
    pw = profile.width - margin_l - margin_r
    ph = profile.height - margin_t - margin_b

    xmin, xmax = min(profile_x), max(profile_x)
    zmin, zmax = min(profile_z), max(profile_z)
    pad_z = max(0.35, (zmax - zmin) * 0.12)
    zmin -= pad_z
    zmax += pad_z
    if xmax <= xmin:
        xmax = xmin + 1.0

    # grid + axes
    for i in range(6):
        y = margin_t + i * ph / 5
        pd.line([(margin_l, y), (margin_l + pw, y)], fill=(210, 210, 210), width=1)
        zlab = zmax - (zmax - zmin) * (i / 5)
        pd.text((4, y - 6), f"{zlab:.1f}", fill=(40, 40, 40), font=_font(10))
    for i in range(6):
        x = margin_l + i * pw / 5
        pd.line([(x, margin_t), (x, margin_t + ph)], fill=(210, 210, 210), width=1)
        xlab = xmin + (xmax - xmin) * (i / 5)
        pd.text((x - 8, margin_t + ph + 8), f"{xlab:.0f}", fill=(40, 40, 40), font=_font(10))
    pd.rectangle([margin_l, margin_t, margin_l + pw, margin_t + ph], outline=(0, 0, 0), width=1)
    pd.text((4, 2), "Elev (m)", fill=(0, 0, 0), font=_font(10))
    pd.text((margin_l + pw // 2 - 20, plan_h - 14), "Dist (m)", fill=(0, 0, 0), font=_font(10))

    pts_px: list[tuple[float, float]] = []
    for x, z in zip(profile_x, profile_z, strict=False):
        px = margin_l + (x - xmin) / (xmax - xmin) * pw
        py = margin_t + (1.0 - (z - zmin) / (zmax - zmin)) * ph
        pts_px.append((px, py))
    if len(pts_px) >= 2:
        pd.line(pts_px, fill=(200, 20, 20), width=3)

    canvas = Image.new("RGB", (width_px, height_px), (255, 255, 255))
    canvas.paste(profile, (10, 30))
    canvas.paste(plan, (width_px // 2 + 10, 30))
    cd = ImageDraw.Draw(canvas)
    title = f'{row.pile_name}_"CH{row.chainage}"'
    cd.text((10, 6), title, fill=(180, 0, 0), font=_font(14))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, format="PNG")
    return out_path


def render_overview_dem(
    dem_rgb_path: Path | None,
    dem_path: Path,
    rows: list[PatioPileRow],
    out_path: Path,
    *,
    title: str,
) -> Path:
    """Yard overview DEM heatmap (not RGB preview) with red pile outlines in DEM CRS."""
    dem_crs = _dem_crs(dem_path)
    all_rings: list[list[list[float]]] = []
    for row in rows:
        all_rings.extend(_row_rings_dem(row, dem_crs))
    if not all_rings:
        raise ValueError("No piles for overview")

    minx, miny, maxx, maxy = _bbox_of_rings(all_rings, pad=40.0)
    data, valid, transform, _cell = _read_window(dem_path, minx, miny, maxx, maxy)
    rgb = _elev_to_rgb(np.where(valid, data, np.nan), valid)
    canvas = Image.fromarray(rgb, mode="RGB")
    # Upscale for readability
    scale = max(1, int(1400 / max(canvas.width, 1)))
    if scale > 1:
        canvas = canvas.resize((canvas.width * scale, canvas.height * scale), Image.Resampling.NEAREST)
    draw = ImageDraw.Draw(canvas)

    def to_px(x: float, y: float) -> tuple[float, float]:
        col = (x - transform.c) / transform.a
        row = (y - transform.f) / transform.e
        return col * scale, row * scale

    for ring in all_rings:
        poly = [to_px(p[0], p[1]) for p in ring]
        if len(poly) >= 3:
            draw.line(poly + [poly[0]], fill=(220, 30, 30), width=2)

    titled = Image.new("RGB", (canvas.width, canvas.height + 40), (255, 255, 255))
    titled.paste(canvas, (0, 40))
    td = ImageDraw.Draw(titled)
    td.text((24, 10), title, fill=(0, 40, 100), font=_font(18))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    titled.save(out_path, format="PNG")
    return out_path


def generate_report_figures(
    report: PatioVolumeReport,
    dem_path: Path,
    out_dir: Path,
    dem_rgb_path: Path | None = None,
) -> dict[str, Any]:
    """Write all figure PNGs for the PDF; return path map."""
    del dem_rgb_path  # overview uses DEM heatmap in DEM CRS (avoids CRS overlay bugs)
    out_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, Any] = {"strips": {}, "lsections": {}, "overviews": {}, "errors": []}

    if report.rows:
        ov = out_dir / "overview-measurement-chainage.png"
        try:
            render_overview_dem(
                None,
                dem_path,
                report.rows,
                ov,
                title="Measurement Chainage & Limits",
            )
            files["overviews"]["chainage_limits"] = str(ov)
        except Exception as exc:  # noqa: BLE001
            files["errors"].append(f"overview: {exc}")

    for patio, rows in sorted(report.by_patio.items()):
        strip = out_dir / f"patio-{patio}-dem-strip.png"
        try:
            render_patio_dem_strip(dem_path, rows, strip)
            files["strips"][patio] = str(strip)
        except Exception as exc:  # noqa: BLE001
            files["errors"].append(f"strip {patio}: {exc}")

        lsec_paths: list[str] = []
        # Cap L-sections so large detections don't hang the job
        stock = [r for r in rows if r.morph_class == "stockpile"] or list(rows)
        stock = sorted(stock, key=lambda r: abs(r.net_volume_m3), reverse=True)[:6]
        for row in stock:
            path = out_dir / f"lsection-{row.pile_name}.png"
            try:
                render_l_section_pair(dem_path, row, path)
                lsec_paths.append(str(path))
            except Exception as exc:  # noqa: BLE001
                files["errors"].append(f"lsec {row.pile_name}: {exc}")
        files["lsections"][patio] = lsec_paths

    return files
