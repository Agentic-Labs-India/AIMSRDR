from __future__ import annotations

import math

from app.schemas import Comparison, PileDelta, PileMetrics, Survey


def _vol(pile: PileMetrics) -> float | None:
    if pile.net_volume_m3 is not None:
        return pile.net_volume_m3
    return pile.total_volume_m3


def _dist2(a: list[float], b: list[float]) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _spatial_pairs(
    left: list[PileMetrics],
    right: list[PileMetrics],
    max_distance_m: float = 75.0,
) -> list[tuple[PileMetrics, PileMetrics]]:
    """Greedy nearest-centroid matching for unnamed / differently named piles."""
    candidates: list[tuple[float, PileMetrics, PileMetrics]] = []
    for a in left:
        if not a.centroid:
            continue
        for b in right:
            if not b.centroid:
                continue
            d2 = _dist2(a.centroid, b.centroid)
            if d2 <= max_distance_m**2:
                candidates.append((d2, a, b))
    candidates.sort(key=lambda item: item[0])

    used_left: set[str] = set()
    used_right: set[str] = set()
    pairs: list[tuple[PileMetrics, PileMetrics]] = []
    for _, a, b in candidates:
        if a.id in used_left or b.id in used_right:
            continue
        used_left.add(a.id)
        used_right.add(b.id)
        pairs.append((a, b))
    return pairs


def compare_surveys(site_id: str, left: Survey, right: Survey) -> Comparison:
    left_named = {p.id: p for p in left.piles if (p.name or p.id).upper().startswith("NC_")}
    right_named = {p.id: p for p in right.piles if (p.name or p.id).upper().startswith("NC_")}

    shared = sorted(set(left_named) & set(right_named))
    deltas: list[PileDelta] = []
    net_parts: list[float] = []
    area_parts: list[float] = []
    notes: list[str] = []
    matched_ids: set[str] = set()

    for pile_id in shared:
        a = left_named[pile_id]
        b = right_named[pile_id]
        matched_ids.add(pile_id)
        vol_from = _vol(a)
        vol_to = _vol(b)
        delta = None
        if vol_from is not None and vol_to is not None:
            delta = vol_to - vol_from
            net_parts.append(delta)
        area_delta = None
        if a.enclosed_area_ha is not None and b.enclosed_area_ha is not None:
            area_delta = b.enclosed_area_ha - a.enclosed_area_ha
            area_parts.append(area_delta)
        deltas.append(
            PileDelta(
                id=pile_id,
                patio=b.patio or a.patio,
                volume_from_m3=vol_from,
                volume_to_m3=vol_to,
                delta_m3=delta,
                area_from_ha=a.enclosed_area_ha,
                area_to_ha=b.enclosed_area_ha,
                delta_area_ha=area_delta,
                centroid=b.centroid or a.centroid,
            )
        )

    # Spatial fallback when names do not overlap (Feb named piles vs March trimmed polygons)
    if len(shared) < 3:
        left_rest = [p for p in left.piles if p.id not in matched_ids]
        right_rest = [p for p in right.piles if p.id not in matched_ids]
        spatial = _spatial_pairs(left_rest, right_rest)
        if spatial:
            notes.append(
                f"Matched {len(spatial)} piles by centroid proximity (≤75 m) because pile NAME IDs "
                f"do not align between {left.label} and {right.label}."
            )
        for a, b in spatial:
            matched_ids.add(a.id)
            matched_ids.add(b.id)
            vol_from = _vol(a)
            vol_to = _vol(b)
            delta = None
            if vol_from is not None and vol_to is not None:
                delta = vol_to - vol_from
                net_parts.append(delta)
            area_delta = None
            if a.enclosed_area_ha is not None and b.enclosed_area_ha is not None:
                area_delta = b.enclosed_area_ha - a.enclosed_area_ha
                area_parts.append(area_delta)
            deltas.append(
                PileDelta(
                    id=f"{a.id}→{b.id}",
                    patio=b.patio or a.patio,
                    volume_from_m3=vol_from,
                    volume_to_m3=vol_to,
                    delta_m3=delta,
                    area_from_ha=a.enclosed_area_ha,
                    area_to_ha=b.enclosed_area_ha,
                    delta_area_ha=area_delta,
                    centroid=b.centroid or a.centroid,
                )
            )

    only_left = sorted(
        p.id for p in left.piles if p.id not in matched_ids and not any(p.id in d.id for d in deltas)
    )
    # recompute unmatched more carefully
    matched_left = set()
    matched_right = set()
    for d in deltas:
        if "→" in d.id:
            left_id, right_id = d.id.split("→", 1)
            matched_left.add(left_id)
            matched_right.add(right_id)
        else:
            matched_left.add(d.id)
            matched_right.add(d.id)
    only_left = sorted(p.id for p in left.piles if p.id not in matched_left)
    only_right = sorted(p.id for p in right.piles if p.id not in matched_right)

    if not net_parts:
        notes.append(
            "Volume deltas unavailable for this pair (March package has no trustworthy independent "
            "volume CSV). Area deltas use polygon footprints; DTM cut/fill heatmap is pending."
        )
    elif area_parts and not math.isclose(sum(area_parts), 0.0, abs_tol=1e-6):
        notes.append(f"Net footprint area change across matched piles: {sum(area_parts):.3f} ha.")

    if only_left:
        notes.append(f"{len(only_left)} piles only in {left.id}.")
    if only_right:
        notes.append(f"{len(only_right)} piles only in {right.id}.")

    cut = sum(d for d in net_parts if d < 0) if net_parts else None
    fill = sum(d for d in net_parts if d > 0) if net_parts else None
    net = sum(net_parts) if net_parts else None

    return Comparison(
        site_id=site_id,
        from_survey_id=left.id,
        to_survey_id=right.id,
        cut_volume_m3=abs(cut) if cut is not None else None,
        fill_volume_m3=fill,
        net_delta_m3=net,
        matched_piles=len(deltas),
        unmatched_from=only_left,
        unmatched_to=only_right,
        piles=deltas,
        notes=notes,
    )
