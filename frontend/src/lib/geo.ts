import type { GeoJSONFeatureCollection } from "@/lib/types";

export type ProjectedRing = number[][];

export type BBox = {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
};

export function collectPositions(geojson: GeoJSONFeatureCollection | null): number[][] {
  if (!geojson) return [];
  const points: number[][] = [];

  const walk = (coords: unknown): void => {
    if (!Array.isArray(coords) || coords.length === 0) return;
    if (typeof coords[0] === "number" && typeof coords[1] === "number") {
      points.push([coords[0] as number, coords[1] as number]);
      return;
    }
    for (const c of coords) walk(c);
  };

  for (const feature of geojson.features) {
    walk(feature.geometry?.coordinates);
  }
  return points;
}

export function bboxFromPoints(points: number[][]): BBox | null {
  if (!points.length) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x, y] of points) {
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
  }
  return { minX, minY, maxX, maxY };
}

export function mergeBBoxes(boxes: Array<BBox | null>): BBox | null {
  const valid = boxes.filter(Boolean) as BBox[];
  if (!valid.length) return null;
  return {
    minX: Math.min(...valid.map((b) => b.minX)),
    minY: Math.min(...valid.map((b) => b.minY)),
    maxX: Math.max(...valid.map((b) => b.maxX)),
    maxY: Math.max(...valid.map((b) => b.maxY)),
  };
}

/** Project UTM meters into a viewBox centered at origin for R3F / SVG. */
export function projectToLocal(x: number, y: number, box: BBox) {
  const cx = (box.minX + box.maxX) / 2;
  const cy = (box.minY + box.maxY) / 2;
  return { x: x - cx, y: y - cy };
}

export function featureRings(geometry: { type: string; coordinates: unknown }): number[][][] {
  const { type, coordinates } = geometry;
  if (type === "Polygon") {
    const rings = coordinates as number[][][];
    return rings?.[0] ? [rings[0]] : [];
  }
  if (type === "MultiPolygon") {
    const polys = coordinates as number[][][][];
    return polys.map((p) => p[0]).filter(Boolean);
  }
  return [];
}

export function svgProject(box: BBox, width: number, height: number, padding = 24) {
  const spanX = Math.max(box.maxX - box.minX, 1);
  const spanY = Math.max(box.maxY - box.minY, 1);
  const scale = Math.min((width - padding * 2) / spanX, (height - padding * 2) / spanY);
  const ox = (width - spanX * scale) / 2;
  const oy = (height - spanY * scale) / 2;
  return (x: number, y: number) => ({
    x: ox + (x - box.minX) * scale,
    y: height - (oy + (y - box.minY) * scale),
  });
}
