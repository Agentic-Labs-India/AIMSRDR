"use client";

import { useMemo } from "react";

import type { GeoJSONFeatureCollection } from "@/lib/types";
import { bboxFromPoints, collectPositions, featureRings, mergeBBoxes, svgProject } from "@/lib/geo";
import { cn } from "@/lib/utils";

type Layer = {
  id: string;
  geojson: GeoJSONFeatureCollection | null;
  fill?: string;
  stroke?: string;
  opacity?: number;
};

type PlanMapProps = {
  layers: Layer[];
  className?: string;
  width?: number;
  height?: number;
};

export function PlanMap({ layers, className, width = 960, height = 560 }: PlanMapProps) {
  const box = useMemo(() => {
    const boxes = layers.map((layer) => bboxFromPoints(collectPositions(layer.geojson)));
    return mergeBBoxes(boxes);
  }, [layers]);

  const project = useMemo(() => (box ? svgProject(box, width, height) : null), [box, width, height]);

  if (!box || !project) {
    return (
      <div className={cn("flex h-full min-h-[320px] items-center justify-center text-sm text-muted-foreground", className)}>
        No vector geometry available for this survey.
      </div>
    );
  }

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className={cn("h-full w-full rounded-xl bg-[radial-gradient(circle_at_20%_20%,#e8eef5,transparent_45%),linear-gradient(160deg,#0f172a_0%,#1e293b_55%,#334155_100%)]", className)}
      role="img"
      aria-label="Survey plan map"
    >
      <defs>
        <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse">
          <path d="M 32 0 L 0 0 0 32" fill="none" stroke="rgba(148,163,184,0.15)" strokeWidth="1" />
        </pattern>
      </defs>
      <rect width={width} height={height} fill="url(#grid)" />
      {layers.map((layer) => {
        if (!layer.geojson) return null;
        return layer.geojson.features.map((feature, idx) => {
          const rings = featureRings(feature.geometry);
          return rings.map((ring, rIdx) => {
            const d = ring
              .map((pt, i) => {
                const p = project(pt[0], pt[1]);
                return `${i === 0 ? "M" : "L"}${p.x} ${p.y}`;
              })
              .join(" ")
              .concat(" Z");
            return (
              <path
                key={`${layer.id}-${feature.id ?? idx}-${rIdx}`}
                d={d}
                fill={layer.fill ?? "rgba(56,189,248,0.35)"}
                stroke={layer.stroke ?? "rgba(125,211,252,0.95)"}
                strokeWidth={1.25}
                opacity={layer.opacity ?? 1}
              />
            );
          });
        });
      })}
    </svg>
  );
}
