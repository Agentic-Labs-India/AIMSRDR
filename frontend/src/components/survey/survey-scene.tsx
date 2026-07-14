"use client";

import { Bounds, OrbitControls } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { useMemo } from "react";
import * as THREE from "three";

import type { GeoJSONFeatureCollection } from "@/lib/types";
import {
  bboxFromPoints,
  collectPositions,
  featureRings,
  mergeBBoxes,
  projectToLocal,
  type BBox,
} from "@/lib/geo";

type Layer = {
  id: string;
  geojson: GeoJSONFeatureCollection | null;
  color: string;
  opacity?: number;
};

type SurveySceneProps = {
  layers: Layer[];
  patioGeo?: GeoJSONFeatureCollection | null;
};

function pileHeight(props: Record<string, unknown>): number {
  const volume = Number(props.NET_VOLUME ?? props.net_volume_m3 ?? props.TOTAL_VOLUME ?? 0);
  if (Number.isFinite(volume) && volume > 0) {
    return Math.min(45, Math.max(3, Math.cbrt(volume) * 0.35));
  }
  const elev = Number(props.AVG_ELEV_M ?? props.avg_elev_m ?? 0);
  if (Number.isFinite(elev) && elev > 0) {
    return Math.min(35, Math.max(2.5, elev * 1.1));
  }
  const area = Number(props.area_ha ?? props.ENCLOSED_A ?? 0);
  if (Number.isFinite(area) && area > 0) {
    return Math.min(30, Math.max(2.5, area * 12));
  }
  return 6;
}

function ExtrudedLayer({
  geojson,
  color,
  opacity = 0.9,
  box,
}: {
  geojson: GeoJSONFeatureCollection;
  color: string;
  opacity?: number;
  box: BBox;
}) {
  const meshes = useMemo(() => {
    return geojson.features.flatMap((feature, idx) => {
      const rings = featureRings(feature.geometry);
      return rings.map((ring, rIdx) => {
        if (ring.length < 3) return null;
        const shape = new THREE.Shape();
        ring.forEach((pt, i) => {
          const p = projectToLocal(pt[0], pt[1], box);
          if (i === 0) shape.moveTo(p.x, -p.y);
          else shape.lineTo(p.x, -p.y);
        });
        const depth = pileHeight(feature.properties ?? {});
        return {
          key: `${String(feature.id ?? idx)}-${rIdx}`,
          shape,
          depth,
        };
      });
    }).filter(Boolean) as Array<{ key: string; shape: THREE.Shape; depth: number }>;
  }, [geojson, box]);

  return (
    <group rotation={[-Math.PI / 2, 0, 0]}>
      {meshes.map((mesh) => (
        <mesh key={mesh.key} position={[0, 0, 0]} castShadow={false} receiveShadow={false}>
          <extrudeGeometry args={[mesh.shape, { depth: mesh.depth, bevelEnabled: false }]} />
          <meshStandardMaterial
            color={color}
            metalness={0.08}
            roughness={0.7}
            transparent
            opacity={opacity}
            side={THREE.DoubleSide}
          />
        </mesh>
      ))}
    </group>
  );
}

function PatioFootprints({ geojson, box }: { geojson: GeoJSONFeatureCollection; box: BBox }) {
  const meshes = useMemo(() => {
    return geojson.features.flatMap((feature, idx) => {
      const rings = featureRings(feature.geometry);
      return rings.map((ring, rIdx) => {
        if (ring.length < 3) return null;
        const shape = new THREE.Shape();
        ring.forEach((pt, i) => {
          const p = projectToLocal(pt[0], pt[1], box);
          if (i === 0) shape.moveTo(p.x, -p.y);
          else shape.lineTo(p.x, -p.y);
        });
        return { key: `patio-${String(feature.id ?? idx)}-${rIdx}`, shape };
      });
    }).filter(Boolean) as Array<{ key: string; shape: THREE.Shape }>;
  }, [geojson, box]);

  return (
    <group rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.05, 0]}>
      {meshes.map((mesh) => (
        <mesh key={mesh.key}>
          <extrudeGeometry args={[mesh.shape, { depth: 0.4, bevelEnabled: false }]} />
          <meshStandardMaterial
            color="#94a3b8"
            transparent
            opacity={0.22}
            side={THREE.DoubleSide}
          />
        </mesh>
      ))}
    </group>
  );
}

function SceneContent({ layers, patioGeo }: SurveySceneProps) {
  const box = useMemo(() => {
    const boxes = [
      ...layers.map((layer) => bboxFromPoints(collectPositions(layer.geojson))),
      bboxFromPoints(collectPositions(patioGeo ?? null)),
    ];
    return mergeBBoxes(boxes);
  }, [layers, patioGeo]);

  const hasGeometry = layers.some((l) => (l.geojson?.features.length ?? 0) > 0);

  if (!box || !hasGeometry) {
    return (
      <mesh>
        <boxGeometry args={[1, 1, 1]} />
        <meshBasicMaterial color="#334155" />
      </mesh>
    );
  }

  return (
    <Bounds fit clip={false} observe margin={1.35}>
      <group>
        {patioGeo ? <PatioFootprints geojson={patioGeo} box={box} /> : null}
        {layers.map((layer) =>
          layer.geojson ? (
            <ExtrudedLayer
              key={layer.id}
              geojson={layer.geojson}
              color={layer.color}
              opacity={layer.opacity}
              box={box}
            />
          ) : null,
        )}
      </group>
    </Bounds>
  );
}

export function SurveyScene({ layers, patioGeo }: SurveySceneProps) {
  const activeLayers = layers.filter((l) => l.geojson && l.geojson.features.length > 0);

  return (
    <div className="relative h-full min-h-[480px] w-full overflow-hidden rounded-xl bg-[#0b1220]">
      {activeLayers.length === 0 ? (
        <div className="flex h-full items-center justify-center text-sm text-slate-300">
          No pile geometry loaded for 3D yet.
        </div>
      ) : (
        <Canvas
          className="h-full w-full"
          camera={{ position: [220, 180, 220], fov: 42, near: 0.1, far: 20000 }}
          dpr={[1, 1.75]}
          gl={{ antialias: true, alpha: false }}
        >
          <color attach="background" args={["#0b1220"]} />
          <ambientLight intensity={0.85} />
          <directionalLight position={[160, 220, 120]} intensity={1.25} />
          <directionalLight position={[-120, 80, -90]} intensity={0.35} />
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.02, 0]}>
            <planeGeometry args={[4000, 4000]} />
            <meshStandardMaterial color="#111827" />
          </mesh>
          <SceneContent layers={activeLayers} patioGeo={patioGeo} />
          <OrbitControls
            makeDefault
            enableDamping
            dampingFactor={0.08}
            maxPolarAngle={Math.PI / 2.05}
            minDistance={20}
            maxDistance={2500}
          />
        </Canvas>
      )}
      <div className="pointer-events-none absolute bottom-3 left-3 rounded-lg bg-black/45 px-2.5 py-1.5 text-[11px] text-slate-200">
        Drag to orbit · scroll to zoom
      </div>
    </div>
  );
}
