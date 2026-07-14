"use client";

import { OrbitControls } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { Component, type ReactNode, Suspense, useEffect, useMemo, useState } from "react";
import * as THREE from "three";

type ViewMode = "points" | "mesh";

type DemTerrainProps = {
  heightmapUrl: string;
  /** Photoreal / ortho texture only — never pass elevation heatmap RGB here. */
  textureUrl?: string | null;
  /** Optional hillshade for natural shading when ortho is missing. */
  hillshadeUrl?: string | null;
  displacementScale?: number;
  exaggerationLabel?: string;
  mode?: ViewMode;
};

export function computeDisplacementScale(opts: {
  elevMinM?: number | null;
  elevMaxM?: number | null;
  groundWidthM?: number | null;
  groundHeightM?: number | null;
  planeH?: number;
  exaggeration?: number;
}) {
  const {
    elevMinM,
    elevMaxM,
    groundWidthM,
    groundHeightM,
    planeH = 120,
    exaggeration = 3,
  } = opts;
  const elevRange =
    elevMinM != null && elevMaxM != null ? Math.max(elevMaxM - elevMinM, 0.5) : 20;
  const groundSpanM = Math.max(groundHeightM || 0, groundWidthM || 0, 200);
  const metersPerUnit = groundSpanM / planeH;
  return Math.max(0.8, (elevRange / metersPerUnit) * exaggeration);
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`Failed to load image: ${url}`));
    img.src = url;
  });
}

function loadTexture(url: string): Promise<THREE.Texture> {
  return new Promise((resolve, reject) => {
    const loader = new THREE.TextureLoader();
    loader.setCrossOrigin("anonymous");
    loader.load(
      url,
      (texture) => {
        texture.needsUpdate = true;
        resolve(texture);
      },
      undefined,
      () => reject(new Error(`Failed to load texture: ${url}`)),
    );
  });
}

function sampleImageData(img: HTMLImageElement): ImageData {
  const canvas = document.createElement("canvas");
  canvas.width = img.naturalWidth || img.width;
  canvas.height = img.naturalHeight || img.height;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) throw new Error("Canvas 2D unavailable");
  ctx.drawImage(img, 0, 0);
  return ctx.getImageData(0, 0, canvas.width, canvas.height);
}

/** Natural site colors (soil / coal / concrete), not a rainbow heatmap. */
function naturalColor(height01: number, shade01: number, tex?: [number, number, number]) {
  if (tex) {
    // Soften ortho with hillshade so it reads like a lit point cloud.
    const lit = 0.45 + 0.55 * shade01;
    return [
      Math.min(1, (tex[0] / 255) * lit),
      Math.min(1, (tex[1] / 255) * lit),
      Math.min(1, (tex[2] / 255) * lit),
    ] as const;
  }
  // Industrial yard palette: charcoal → taupe → warm sand
  const h = height01;
  const s = shade01;
  const r = 0.18 + 0.42 * h + 0.28 * s;
  const g = 0.17 + 0.36 * h + 0.22 * s;
  const b = 0.16 + 0.30 * h + 0.18 * s;
  return [
    Math.min(1, r),
    Math.min(1, g),
    Math.min(1, b),
  ] as const;
}

function PointCloudDem({
  heightmapUrl,
  textureUrl,
  hillshadeUrl,
  displacementScale = 8,
}: DemTerrainProps) {
  const [geometry, setGeometry] = useState<THREE.BufferGeometry | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let geo: THREE.BufferGeometry | null = null;

    async function run() {
      setError(null);
      setGeometry(null);
      try {
        const heightImg = await loadImage(heightmapUrl);
        const shadeImg = hillshadeUrl
          ? await loadImage(hillshadeUrl).catch(() => null)
          : null;
        // Only use true imagery (ortho). Never heatmap RGB.
        const colorImg = textureUrl
          ? await loadImage(textureUrl).catch(() => null)
          : null;

        if (cancelled) return;

        const height = sampleImageData(heightImg);
        const shade = shadeImg ? sampleImageData(shadeImg) : null;
        const color = colorImg ? sampleImageData(colorImg) : null;

        const w = height.width;
        const h = height.height;
        const aspect = w / Math.max(h, 1);
        const planeW = 120 * aspect;
        const planeH = 120;

        // Density: keep ~180k–250k points for performance.
        const target = 220_000;
        const step = Math.max(1, Math.ceil(Math.sqrt((w * h) / target)));

        const positions: number[] = [];
        const colors: number[] = [];

        for (let y = 0; y < h; y += step) {
          for (let x = 0; x < w; x += step) {
            const i = (y * w + x) * 4;
            const elevByte = height.data[i];
            // Nodata / empty background in our heightmaps is near black.
            if (elevByte < 3) continue;

            const height01 = elevByte / 255;
            const shade01 = shade ? shade.data[i] / 255 : 0.65 + 0.35 * height01;
            const u = x / (w - 1);
            const v = y / (h - 1);
            const px = (u - 0.5) * planeW;
            const pz = (v - 0.5) * planeH;
            const py = (height01 - 0.45) * displacementScale;

            let tex: [number, number, number] | undefined;
            if (color) {
              const cx = Math.min(color.width - 1, Math.floor(u * (color.width - 1)));
              const cy = Math.min(color.height - 1, Math.floor(v * (color.height - 1)));
              const ci = (cy * color.width + cx) * 4;
              // Skip near-black ortho/nodata samples
              if (color.data[ci] + color.data[ci + 1] + color.data[ci + 2] > 24) {
                tex = [color.data[ci], color.data[ci + 1], color.data[ci + 2]];
              }
            }

            const [r, g, b] = naturalColor(height01, shade01, tex);
            positions.push(px, py, pz);
            colors.push(r, g, b);
          }
        }

        if (positions.length < 30) {
          throw new Error("Not enough valid DEM samples for point cloud");
        }

        geo = new THREE.BufferGeometry();
        geo.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
        geo.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
        geo.computeBoundingSphere();
        if (!cancelled) setGeometry(geo);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Point cloud failed");
        }
      }
    }

    void run();
    return () => {
      cancelled = true;
      geo?.dispose();
    };
  }, [heightmapUrl, textureUrl, hillshadeUrl, displacementScale]);

  if (error || !geometry) return null;

  return (
    <points geometry={geometry}>
      <pointsMaterial
        vertexColors
        size={0.85}
        sizeAttenuation
        depthWrite
        transparent={false}
      />
    </points>
  );
}

function TerrainMesh({
  heightmapUrl,
  textureUrl,
  hillshadeUrl,
  displacementScale = 8,
}: DemTerrainProps) {
  const [heightMap, setHeightMap] = useState<THREE.Texture | null>(null);
  const [colorMap, setColorMap] = useState<THREE.Texture | null>(null);

  useEffect(() => {
    let cancelled = false;
    const textures: THREE.Texture[] = [];

    async function run() {
      setHeightMap(null);
      setColorMap(null);
      try {
        const height = await loadTexture(heightmapUrl);
        height.colorSpace = THREE.NoColorSpace;
        height.wrapS = height.wrapT = THREE.ClampToEdgeWrapping;
        textures.push(height);

        // Prefer ortho imagery; else hillshade (natural gray), never heatmap.
        const preferred = textureUrl || hillshadeUrl || heightmapUrl;
        const color = await loadTexture(preferred);
        color.colorSpace = THREE.SRGBColorSpace;
        color.wrapS = color.wrapT = THREE.ClampToEdgeWrapping;
        textures.push(color);

        if (!cancelled) {
          setHeightMap(height);
          setColorMap(color);
        }
      } catch {
        if (!cancelled) {
          setHeightMap(null);
          setColorMap(null);
        }
      }
    }

    void run();
    return () => {
      cancelled = true;
      for (const texture of textures) texture.dispose();
    };
  }, [heightmapUrl, textureUrl, hillshadeUrl]);

  const { width, height } = useMemo(() => {
    const img = heightMap?.image as HTMLImageElement | undefined;
    return {
      width: img?.width || 256,
      height: img?.height || 256,
    };
  }, [heightMap]);

  if (!heightMap || !colorMap) return null;

  const aspect = width / Math.max(height, 1);
  const planeW = 120 * aspect;
  const planeH = 120;

  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]}>
      <planeGeometry args={[planeW, planeH, 220, 220]} />
      <meshStandardMaterial
        map={colorMap}
        displacementMap={heightMap}
        displacementScale={displacementScale}
        displacementBias={-displacementScale * 0.45}
        roughness={0.9}
        metalness={0.02}
      />
    </mesh>
  );
}

class SceneErrorBoundary extends Component<
  { children: ReactNode; fallback: ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) return this.props.fallback;
    return this.props.children;
  }
}

export function DemTerrainScene({
  heightmapUrl,
  textureUrl,
  hillshadeUrl,
  displacementScale = 8,
  exaggerationLabel,
  mode: modeProp,
}: DemTerrainProps) {
  const [mode, setMode] = useState<ViewMode>(modeProp ?? "points");

  if (!heightmapUrl) {
    return (
      <div className="flex h-full min-h-[360px] items-center justify-center rounded-xl bg-slate-950 text-sm text-slate-300">
        DEM heightmap not ready yet. Run backend processing in Docker (GDAL).
      </div>
    );
  }

  const fallback = (
    <div className="flex h-full min-h-[360px] items-center justify-center rounded-xl bg-slate-950 px-4 text-center text-sm text-slate-300">
      3D point cloud could not load. Check DEM heightmap / hillshade media URLs.
    </div>
  );

  return (
    <SceneErrorBoundary fallback={fallback}>
      <div className="relative h-full min-h-[420px] w-full overflow-hidden rounded-xl bg-[#07111f]">
        <div className="absolute left-3 top-3 z-10 flex gap-1 rounded-lg border border-white/10 bg-black/55 p-1">
          <button
            type="button"
            onClick={() => setMode("points")}
            className={`rounded-md px-2.5 py-1 text-[11px] ${
              mode === "points"
                ? "bg-sky-500/30 text-sky-100"
                : "text-slate-300 hover:bg-white/10"
            }`}
          >
            Point cloud
          </button>
          <button
            type="button"
            onClick={() => setMode("mesh")}
            className={`rounded-md px-2.5 py-1 text-[11px] ${
              mode === "mesh"
                ? "bg-sky-500/30 text-sky-100"
                : "text-slate-300 hover:bg-white/10"
            }`}
          >
            Mesh
          </button>
        </div>

        <Canvas camera={{ position: [0, 70, 95], fov: 40, near: 0.1, far: 5000 }} dpr={[1, 1.75]}>
          <color attach="background" args={["#0a1220"]} />
          <ambientLight intensity={0.85} />
          <directionalLight position={[60, 110, 40]} intensity={1.25} />
          <directionalLight position={[-40, 40, -20]} intensity={0.35} />
          <Suspense fallback={null}>
            {mode === "points" ? (
              <PointCloudDem
                key={`pts|${heightmapUrl}|${textureUrl ?? ""}|${hillshadeUrl ?? ""}|${displacementScale}`}
                heightmapUrl={heightmapUrl}
                textureUrl={textureUrl}
                hillshadeUrl={hillshadeUrl}
                displacementScale={displacementScale}
              />
            ) : (
              <TerrainMesh
                key={`mesh|${heightmapUrl}|${textureUrl ?? ""}|${hillshadeUrl ?? ""}|${displacementScale}`}
                heightmapUrl={heightmapUrl}
                textureUrl={textureUrl}
                hillshadeUrl={hillshadeUrl}
                displacementScale={displacementScale}
              />
            )}
          </Suspense>
          <axesHelper args={[18]} />
          <OrbitControls makeDefault enableDamping maxPolarAngle={Math.PI / 2.05} />
        </Canvas>

        <div className="pointer-events-none absolute bottom-3 left-3 rounded-md bg-black/50 px-2 py-1 text-[11px] text-slate-200">
          3D point cloud · drag to orbit · scroll zoom
          {exaggerationLabel ? ` · ${exaggerationLabel}` : null}
        </div>
      </div>
    </SceneErrorBoundary>
  );
}
