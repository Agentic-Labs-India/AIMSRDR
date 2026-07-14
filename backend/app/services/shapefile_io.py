from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import shapefile


SHAPEFILE_SIDECARS = (".shp", ".dbf", ".shx", ".prj", ".cpg", ".sbn", ".sbx")


def shapefile_complete(path: Path) -> bool:
    return path.suffix.lower() == ".shp" and path.exists() and path.with_suffix(".dbf").exists()


def _ring_area(ring: list[list[float]]) -> float:
    if len(ring) < 3:
        return 0.0
    area = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[i + 1][0], ring[i + 1][1]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _centroid(ring: list[list[float]]) -> list[float] | None:
    if len(ring) < 3:
        return None
    a = 0.0
    cx = 0.0
    cy = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[i + 1][0], ring[i + 1][1]
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(a) < 1e-12:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return [sum(xs) / len(xs), sum(ys) / len(ys)]
    a *= 0.5
    return [cx / (6.0 * a), cy / (6.0 * a)]


def _coords_from_shape(shape: shapefile.Shape) -> Any:
    parts = list(shape.parts) + [len(shape.points)]
    rings: list[list[list[float]]] = []
    for i in range(len(parts) - 1):
        start, end = parts[i], parts[i + 1]
        ring = [[float(x), float(y)] for x, y in shape.points[start:end]]
        if ring and ring[0] != ring[-1]:
            ring.append(ring[0][:])
        if len(ring) >= 4:
            rings.append(ring)
    if not rings:
        return None
    if shape.shapeType in (shapefile.POLYLINE, shapefile.POLYLINEM, shapefile.POLYLINEZ, 3, 13, 23):
        return rings
    # Polygon: first ring exterior, others holes
    if len(rings) == 1:
        return rings[0]
    return rings


def shapefile_to_geojson(shp_path: Path, feature_id_prefix: str = "") -> dict[str, Any]:
    reader = shapefile.Reader(str(shp_path))
    fields = [f[0] for f in reader.fields[1:]]
    features: list[dict[str, Any]] = []

    for idx, (shape, record) in enumerate(zip(reader.shapes(), reader.records(), strict=False)):
        props = {fields[i]: record[i] for i in range(len(fields))}
        # Normalize keys / values for JSON
        clean_props: dict[str, Any] = {}
        for k, v in props.items():
            if v is None:
                continue
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                continue
            clean_props[k] = v if not isinstance(v, bytes) else v.decode("utf-8", errors="ignore")

        name = (
            clean_props.get("NAME")
            or clean_props.get("Name")
            or clean_props.get("Id")
            or clean_props.get("ID")
            or f"{feature_id_prefix}{idx + 1}"
        )
        clean_props["feature_id"] = str(name)

        coords = _coords_from_shape(shape)
        if coords is None:
            continue

        if shape.shapeType in (shapefile.POLYLINE, shapefile.POLYLINEM, shapefile.POLYLINEZ, 3, 13, 23):
            geom_type = "MultiLineString" if len(coords) > 1 else "LineString"
            geometry = {
                "type": geom_type,
                "coordinates": coords if geom_type == "MultiLineString" else coords[0],
            }
            centroid = None
            area_m2 = None
        else:
            if isinstance(coords[0][0], (int, float)):
                geometry = {"type": "Polygon", "coordinates": [coords]}
                exterior = coords
            else:
                geometry = {"type": "Polygon", "coordinates": coords}
                exterior = coords[0]
            centroid = _centroid(exterior)
            area_m2 = _ring_area(exterior)
            if centroid:
                clean_props["centroid_x"] = centroid[0]
                clean_props["centroid_y"] = centroid[1]
            if area_m2 is not None:
                clean_props["area_m2"] = area_m2
                clean_props["area_ha"] = area_m2 / 10000.0

        features.append(
            {
                "type": "Feature",
                "id": str(name),
                "properties": clean_props,
                "geometry": geometry,
            }
        )

    return {"type": "FeatureCollection", "features": features}


def write_geojson(path: Path, geojson: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")


def merge_feature_collections(*collections: dict[str, Any]) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for collection in collections:
        features.extend(collection.get("features", []))
    return {"type": "FeatureCollection", "features": features}
