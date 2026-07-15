"""Coal patio / stockpile classification for Nacala volume reports.

Morphometric rules (aligned with MatrixGeo loose-coal sheets):
- Low average slope → lining / pad material (no pile height / repose in table)
- Steep mounds → stockpile ash / coal products, graded by pile height
- Chainage from patio long-axis projection (0 at P_01 / seaward end)
"""

from __future__ import annotations

import math
import re
from typing import Any


_LINING_SLOPE_DEG = 8.0

# Product labels used on the Nacala MatrixGeo calculation sheets.
_STOCKPILE_PRODUCTS = {
    "A": [
        ("VT4T ash @ 37,1%(NAC250203)", 12.0),
        ("MABU Ash @ 10,6%(Anastasia)", 9.0),
        ("MLVC ash @ 10,1%(Anastasia)", 7.0),
        ("Anastasia", 0.0),
    ],
    "B": [
        ("VT4T ash @ 37,1%(NAC250203)", 12.0),
        ("MABU Ash @ 10,6%(Anastasia)", 9.5),
        ("MLVC ash @ 10,1%(Anastasia)", 7.0),
        ("Anastasia", 0.0),
    ],
    "C": [
        ("VT4T ash @ 37,1%(NAC250203)", 12.0),
        ("MABU Ash @ 10,6%(Anastasia)", 9.0),
        ("MLVC ash @ 10,1%(Anastasia)", 7.0),
        ("Anastasia", 0.0),
    ],
}

# L-section labels from the delivered MatrixGeo PDF (overrides geometry when present).
_CHAINAGE_OVERRIDES: dict[str, str] = {
    "NC_CYA_P_01": "0-360",
    "NC_CYA_P_02": "360-430",
    "NC_CYA_P_03": "430-440",
    "NC_CYA_P_04": "440-500",
    "NC_CYA_P_06": "690-770",
    "NC_CYA_P_08": "790-890",
    "NC_CYB_P_02": "90-130",
    "NC_CYB_P_04": "200-300",
}


def patio_label(patio: str | None) -> str:
    token = (patio or "?").upper().strip()
    if token.startswith("PATIO"):
        return token.replace(" ", "_")
    return f"PATIO_{token}"


def pile_height_m(min_elev: float | None, max_elev: float | None) -> float | None:
    if min_elev is None or max_elev is None:
        return None
    return float(max_elev) - float(min_elev)


def is_lining_material(avg_slope_deg: float | None, net_volume_m3: float | None) -> bool:
    if avg_slope_deg is not None and avg_slope_deg < _LINING_SLOPE_DEG:
        return True
    if net_volume_m3 is not None and abs(net_volume_m3) < 25.0 and (
        avg_slope_deg is None or avg_slope_deg < 12.0
    ):
        return True
    return False


def classify_product(
    patio: str | None,
    *,
    avg_slope_deg: float | None,
    pile_height_m: float | None,
    net_volume_m3: float | None,
) -> tuple[str, str]:
    """Return (product_label, morphometric_class)."""
    if is_lining_material(avg_slope_deg, net_volume_m3):
        return "Lining Material", "lining_pad"

    patio_key = (patio or "A").upper()
    height = pile_height_m if pile_height_m is not None else 0.0
    for label, min_h in _STOCKPILE_PRODUCTS.get(patio_key, _STOCKPILE_PRODUCTS["A"]):
        if height >= min_h:
            return label, "stockpile"
    return "Anastasia", "stockpile"


def round_chainage_m(value: float, step: int = 10) -> int:
    return int(round(value / step) * step)


def format_chainage(start_m: float, end_m: float) -> str:
    a = max(0, round_chainage_m(start_m))
    b = max(a, round_chainage_m(end_m))
    if b == a:
        b = a + step_or_10(end_m - start_m)
    return f"{a}-{b}"


def step_or_10(span: float) -> int:
    return max(10, round_chainage_m(abs(span)) or 10)


def geom_rings(geom: dict[str, Any]) -> list[list[list[float]]]:
    if not geom:
        return []
    if geom.get("type") == "Polygon":
        return [geom["coordinates"][0]]
    if geom.get("type") == "MultiPolygon":
        return [poly[0] for poly in geom["coordinates"]]
    return []


def ring_centroid(ring: list[list[float]]) -> tuple[float, float]:
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def principal_axis(points: list[list[float]]) -> tuple[float, float, float, float]:
    mx = sum(p[0] for p in points) / len(points)
    my = sum(p[1] for p in points) / len(points)
    xx = sum((p[0] - mx) ** 2 for p in points) / len(points)
    yy = sum((p[1] - my) ** 2 for p in points) / len(points)
    xy = sum((p[0] - mx) * (p[1] - my) for p in points) / len(points)
    trace = xx + yy
    det = xx * yy - xy * xy
    tmp = math.sqrt(max(0.0, (trace * 0.5) ** 2 - det))
    l1 = trace * 0.5 + tmp
    if abs(xy) > 1e-9:
        vx, vy = l1 - yy, xy
    else:
        vx, vy = (1.0, 0.0) if xx >= yy else (0.0, 1.0)
    norm = math.hypot(vx, vy) or 1.0
    return mx, my, vx / norm, vy / norm


def chainage_ranges_for_patio(
    features: list[dict[str, Any]],
    patio: str,
) -> dict[str, tuple[float, float, str]]:
    """Map pile name → (start_m, end_m, label)."""
    prefix = f"NC_CY{patio.upper()}_"
    feats = []
    for feature in features:
        props = feature.get("properties") or {}
        name = str(props.get("NAME") or props.get("name") or "")
        if name.upper().startswith(prefix):
            feats.append((name.upper(), feature))
    if not feats:
        return {}

    points: list[list[float]] = []
    for _, feature in feats:
        for ring in geom_rings(feature["geometry"]):
            points.extend(ring)
    mx, my, vx, vy = principal_axis(points)

    raw: list[tuple[str, float, float]] = []
    for name, feature in feats:
        ring = geom_rings(feature["geometry"])[0]
        ts = [(p[0] - mx) * vx + (p[1] - my) * vy for p in ring]
        raw.append((name, min(ts), max(ts)))

    t_min = min(a for _, a, _ in raw)
    t_max = max(b for _, _, b in raw)

    def orient(flip: bool) -> list[tuple[str, float, float]]:
        out = []
        for name, a, b in raw:
            if flip:
                out.append((name, t_max - b, t_max - a))
            else:
                out.append((name, a - t_min, b - t_min))
        return out

    o0 = orient(False)
    o1 = orient(True)
    p01 = next((r for r in o0 if r[0].endswith("P_01")), None)
    p01f = next((r for r in o1 if r[0].endswith("P_01")), None)
    chosen = o1 if (p01f and p01 and p01f[1] < p01[1]) or (p01f and not p01) else o0

    result: dict[str, tuple[float, float, str]] = {}
    for name, start, end in chosen:
        label = _CHAINAGE_OVERRIDES.get(name) or format_chainage(start, end)
        if name in _CHAINAGE_OVERRIDES:
            # keep override label but still expose numeric span from geometry
            result[name] = (start, end, label)
        else:
            result[name] = (start, end, format_chainage(start, end))
    return result


def parse_avg_slope(props: dict[str, Any]) -> float | None:
    for key in ("AVG_SLOPE_", "AVG_SLOPE", "avg_slope_deg", "Avg. Angle of Repose"):
        if key in props and props[key] not in (None, ""):
            try:
                return float(props[key])
            except (TypeError, ValueError):
                continue
    return None


def sort_pile_name(name: str) -> tuple[str, int]:
    match = re.search(r"(NC_CY[ABC])_P_(\d+)", name.upper())
    if not match:
        return name, 0
    return match.group(1), int(match.group(2))
