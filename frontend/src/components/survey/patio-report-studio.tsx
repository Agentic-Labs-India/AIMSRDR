"use client";

import { Download, FileUp, Loader2, ArrowLeft } from "lucide-react";
import { useState } from "react";

import {
  computeDisplacementScale,
  DemTerrainScene,
} from "@/components/survey/dem-terrain-scene";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getApiBase, mediaUrl, type PatioVolumeReportBundle } from "@/lib/api";
import { formatNumber } from "@/lib/format";

type UploadJobStart = {
  ok: boolean;
  job_id: string;
  status: string;
  progress: number;
  step: string;
  poll_url: string;
};

type UploadJobStatus = {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  progress: number;
  step: string;
  error: string | null;
  result: (PatioVolumeReportBundle & {
    rasters?: {
      dem_preview_url?: string;
      dem_rgb_url?: string;
      dem_heightmap_url?: string;
      dem_hillshade_url?: string;
      dem_metadata?: {
        elevation_stats?: { minimum?: number; maximum?: number; mean?: number };
        extent?: { min_x?: number; max_x?: number; min_y?: number; max_y?: number };
      };
    };
    piles_geojson_url?: string;
  }) | null;
};

function FilePick({
  label,
  hint,
  accept,
  multiple,
  files,
  onChange,
  required,
}: {
  label: string;
  hint: string;
  accept: string;
  multiple?: boolean;
  files: File[];
  onChange: (files: File[]) => void;
  required?: boolean;
}) {
  return (
    <label className="block rounded-xl border border-white/15 bg-white/5 px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <div className="text-sm font-medium text-white">
            {label}
            {required ? <span className="text-sky-300"> *</span> : null}
          </div>
          <div className="mt-0.5 text-xs text-slate-400">{hint}</div>
        </div>
        <FileUp className="size-4 shrink-0 text-slate-400" />
      </div>
      <input
        type="file"
        accept={accept}
        multiple={multiple}
        className="mt-3 block w-full text-xs text-slate-300 file:mr-3 file:rounded-md file:border-0 file:bg-sky-500/20 file:px-3 file:py-1.5 file:text-sky-100"
        onChange={(e) => onChange(Array.from(e.target.files ?? []))}
      />
      {files.length ? (
        <ul className="mt-2 space-y-0.5 text-[11px] text-slate-300">
          {files.map((f) => (
            <li key={`${f.name}-${f.size}`} className="truncate">
              {f.name} · {(f.size / 1_000_000).toFixed(2)} MB
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-[11px] text-slate-500">No file selected</p>
      )}
    </label>
  );
}

function byExt(files: File[], ext: string) {
  return files.find((f) => f.name.toLowerCase().endsWith(ext)) ?? null;
}

export function PatioReportStudio() {
  const [demFiles, setDemFiles] = useState<File[]>([]);
  const [orthoFiles, setOrthoFiles] = useState<File[]>([]);
  const [surveyDate, setSurveyDate] = useState("2025-02-24");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [step, setStep] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadJobStatus["result"]>(null);
  const [exaggeration, setExaggeration] = useState(3);
  const [view, setView] = useState<"upload" | "dashboard">("upload");

  async function generate() {
    setError(null);
    setResult(null);
    setProgress(0);
    setStep(null);

    const demTif = byExt(demFiles, ".tif") || byExt(demFiles, ".tiff");
    const demTfw = byExt(demFiles, ".tfw");
    const demPrj = byExt(demFiles, ".prj");
    if (!demTif) {
      setError("Select the DEM .tif (+ .tfw + .prj together)");
      return;
    }

    const body = new FormData();
    body.append("dem_tif", demTif);
    if (demTfw) body.append("dem_tfw", demTfw);
    if (demPrj) body.append("dem_prj", demPrj);
    const orthoEcw = byExt(orthoFiles, ".ecw");
    const orthoEww = byExt(orthoFiles, ".eww");
    const orthoPrj = byExt(orthoFiles, ".prj");
    if (orthoEcw) body.append("ortho_ecw", orthoEcw);
    if (orthoEww) body.append("ortho_eww", orthoEww);
    if (orthoPrj) body.append("ortho_prj", orthoPrj);
    body.append("survey_date", surveyDate);
    body.append("site_name", "Nacala Port & Coal Field");

    setBusy(true);
    setStep("Uploading files…");
    try {
      const startRes = await fetch(`${getApiBase()}/api/v1/reports/patio-volumes/upload`, {
        method: "POST",
        body,
      });
      const startText = await startRes.text();
      if (!startRes.ok) {
        let detail = startText;
        try {
          detail = JSON.parse(startText).detail ?? startText;
        } catch {
          /* keep */
        }
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }
      const started = JSON.parse(startText) as UploadJobStart;
      setStep(started.step);
      setProgress(5);

      // Poll background job (keeps UI alive; API worker stays healthy)
      let latest: UploadJobStatus | null = null;
      for (;;) {
        await new Promise((r) => setTimeout(r, 1200));
        const stRes = await fetch(
          `${getApiBase()}/api/v1/reports/patio-volumes/jobs/${started.job_id}`,
          { cache: "no-store" },
        );
        if (!stRes.ok) throw new Error(`Job status failed (${stRes.status})`);
        latest = (await stRes.json()) as UploadJobStatus;
        setProgress(latest.progress);
        setStep(latest.step);
        if (latest.status === "completed" || latest.status === "failed") break;
      }

      if (!latest || latest.status === "failed") {
        throw new Error(latest?.error || "Processing failed");
      }
      setResult(latest.result);
      setView("dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Report generation failed");
    } finally {
      setBusy(false);
    }
  }

  if (view === "dashboard" && result) {
    return (
      <UploadDashboard
        result={result}
        exaggeration={exaggeration}
        onExaggeration={setExaggeration}
        onBack={() => setView("upload")}
      />
    );
  }

  return (
    <div className="min-h-screen bg-[#0b1220] text-slate-100">
      <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6">
        <header className="mb-8">
          <div className="text-xs uppercase tracking-[0.2em] text-sky-400">AIMS RDR</div>
          <h1 className="mt-1 text-2xl font-semibold text-white">
            Coal Patio Volume Detection
          </h1>
          <p className="mt-2 text-sm text-slate-400">
            Select DEM (.tif + .tfw + .prj) and optional ortho (.ecw + .eww + .prj). Processing runs
            in the background — then you get the 3D / heatmap dashboard + PDF.
          </p>
        </header>

        <Card className="border-white/10 bg-[#0f172a] text-slate-100">
          <CardHeader>
            <CardTitle className="text-white">Select files</CardTitle>
            <CardDescription className="text-slate-400">
              Multi-select sidecars together. Large DEMs can take a few minutes after upload.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <FilePick
              label="DEM package"
              hint="Required: .tif · Recommended: .tfw + .prj"
              accept=".tif,.tiff,.tfw,.prj"
              multiple
              files={demFiles}
              onChange={setDemFiles}
              required
            />
            <FilePick
              label="Ortho package"
              hint="Optional: .ecw + .eww + .prj"
              accept=".ecw,.eww,.prj"
              multiple
              files={orthoFiles}
              onChange={setOrthoFiles}
            />
            <label className="block text-xs text-slate-300">
              Survey date
              <input
                type="date"
                value={surveyDate}
                onChange={(e) => setSurveyDate(e.target.value)}
                className="mt-1 h-9 w-full rounded-lg border border-white/15 bg-slate-900 px-2 text-sm text-white"
              />
            </label>

            <Button
              type="button"
              className="w-full bg-sky-500 text-white hover:bg-sky-400"
              disabled={busy}
              onClick={() => void generate()}
            >
              {busy ? (
                <>
                  <Loader2 className="mr-2 size-4 animate-spin" />
                  {step || "Working…"}
                </>
              ) : (
                "Upload & generate"
              )}
            </Button>

            {busy ? (
              <div className="space-y-1">
                <div className="h-2 overflow-hidden rounded-full bg-white/10">
                  <div
                    className="h-full bg-sky-400 transition-all"
                    style={{ width: `${Math.max(4, progress)}%` }}
                  />
                </div>
                <p className="text-xs text-slate-400">
                  {Math.round(progress)}% · {step}
                </p>
              </div>
            ) : null}

            {error ? (
              <p className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
                {error}
              </p>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function UploadDashboard({
  result,
  exaggeration,
  onExaggeration,
  onBack,
}: {
  result: NonNullable<UploadJobStatus["result"]>;
  exaggeration: number;
  onExaggeration: (v: number) => void;
  onBack: () => void;
}) {
  const rasters = result.rasters;
  const elev = rasters?.dem_metadata?.elevation_stats;
  const extent = rasters?.dem_metadata?.extent;
  const groundWidthM =
    extent?.min_x != null && extent?.max_x != null ? Math.abs(extent.max_x - extent.min_x) : null;
  const groundHeightM =
    extent?.min_y != null && extent?.max_y != null ? Math.abs(extent.max_y - extent.min_y) : null;
  const displacementScale = computeDisplacementScale({
    elevMinM: elev?.minimum,
    elevMaxM: elev?.maximum,
    groundWidthM,
    groundHeightM,
    exaggeration,
  });

  // Bust browser cache after heightmap encoding change (full min–max, not p98 clip).
  const bust = (url: string | null | undefined, tag: string) => {
    if (!url) return "";
    return `${url}${url.includes("?") ? "&" : "?"}v=${tag}`;
  };
  const heightmap = bust(mediaUrl(rasters?.dem_heightmap_url), "hm-minmax");
  const hillshade = mediaUrl(rasters?.dem_hillshade_url);
  const demRgb = bust(mediaUrl(rasters?.dem_rgb_url), "hm-minmax");
  const demPreview = bust(mediaUrl(rasters?.dem_preview_url), "hm-minmax");
  const pdfHref = mediaUrl(result.pdf_url);

  return (
    <div className="min-h-screen bg-[#0b1220] text-slate-100">
      <div className="mx-auto max-w-7xl space-y-4 px-4 py-6 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <button
              type="button"
              onClick={onBack}
              className="mb-1 inline-flex items-center gap-1 text-xs text-slate-400 hover:text-white"
            >
              <ArrowLeft className="size-3.5" /> New upload
            </button>
            <h1 className="text-xl font-semibold text-white">Survey dashboard</h1>
            <p className="text-sm text-slate-400">
              {result.summary.pile_count} piles ·{" "}
              {formatNumber(result.summary.total_volume_m3, 0)} m³ net · DEM auto-detect
            </p>
          </div>
          {pdfHref ? (
            <a
              href={`${pdfHref}?download=true`}
              className="inline-flex h-9 items-center rounded-md border border-white/30 px-3 text-sm text-foreground hover:bg-white/10"
            >
              <Download className="mr-2 size-4" />
              Download PDF
            </a>
          ) : null}
        </div>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            label="Elev range"
            value={
              elev?.minimum != null && elev?.maximum != null
                ? `${formatNumber(elev.minimum, 1)}–${formatNumber(elev.maximum, 1)} m`
                : "—"
            }
          />
          <Stat
            label="Patio A"
            value={`${formatNumber(result.summary.totals_by_patio?.A ?? 0, 0)} m³`}
          />
          <Stat
            label="Patio B"
            value={`${formatNumber(result.summary.totals_by_patio?.B ?? 0, 0)} m³`}
          />
          <Stat
            label="Patio C"
            value={`${formatNumber(result.summary.totals_by_patio?.C ?? 0, 0)} m³`}
          />
        </div>

        <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
          <Card className="border-white/10 bg-[#0f172a] text-slate-100">
            <CardHeader className="flex flex-row items-center justify-between space-y-0">
              <div>
                <CardTitle className="text-white">3D DEM</CardTitle>
                <CardDescription className="text-slate-400">
                  Point cloud / mesh from DEM heightmap
                </CardDescription>
              </div>
              <label className="flex items-center gap-2 text-xs text-slate-300">
                Z
                <input
                  type="range"
                  min={1}
                  max={8}
                  step={0.5}
                  value={exaggeration}
                  onChange={(e) => onExaggeration(Number(e.target.value))}
                  className="w-28 accent-sky-400"
                />
                {exaggeration.toFixed(1)}×
              </label>
            </CardHeader>
            <CardContent>
              <div className="h-[460px]">
                {heightmap ? (
                  <DemTerrainScene
                    heightmapUrl={heightmap}
                    textureUrl={demRgb}
                    hillshadeUrl={hillshade}
                    displacementScale={displacementScale}
                    exaggerationLabel={`${exaggeration.toFixed(1)}× Z`}
                    mode="points"
                  />
                ) : (
                  <div className="flex h-full items-center justify-center text-sm text-slate-400">
                    Heightmap not ready
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-4">
            <Card className="border-white/10 bg-[#0f172a] text-slate-100">
              <CardHeader>
                <CardTitle className="text-white">DEM RGB heatmap</CardTitle>
              </CardHeader>
              <CardContent>
                {demRgb || demPreview ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={demRgb || demPreview || ""}
                    alt="DEM RGB"
                    className="max-h-[280px] w-full rounded-lg object-contain"
                  />
                ) : (
                  <p className="text-sm text-slate-400">No DEM preview</p>
                )}
              </CardContent>
            </Card>
            <Card className="border-white/10 bg-[#0f172a] text-slate-100">
              <CardHeader>
                <CardTitle className="text-white">Hillshade</CardTitle>
              </CardHeader>
              <CardContent>
                {hillshade ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={hillshade}
                    alt="Hillshade"
                    className="max-h-[220px] w-full rounded-lg object-contain"
                  />
                ) : (
                  <p className="text-sm text-slate-400">No hillshade</p>
                )}
              </CardContent>
            </Card>
          </div>
        </div>

        {Object.entries(result.data?.patios || {})
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([patio, block]) => (
            <Card key={patio} className="border-white/10 bg-[#0f172a] text-slate-100">
              <CardHeader>
                <CardTitle className="text-white">
                  PATIO {patio} · {formatNumber(block.total_volume_m3, 2)} m³
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto rounded-lg border border-white/10">
                  <table className="min-w-full text-left text-xs">
                    <thead className="text-[11px] uppercase text-slate-400">
                      <tr>
                        <th className="px-3 py-2">Pile</th>
                        <th className="px-3 py-2">Vol m³</th>
                        <th className="px-3 py-2">Area ha</th>
                        <th className="px-3 py-2">Chainage</th>
                        <th className="px-3 py-2">Product</th>
                      </tr>
                    </thead>
                    <tbody>
                      {block.piles.map((p) => (
                        <tr key={p.pile_name} className="border-t border-white/10">
                          <td className="px-3 py-1.5 font-mono text-[11px]">{p.pile_name}</td>
                          <td className="px-3 py-1.5 tabular-nums">
                            {formatNumber(p.net_volume_m3, 2)}
                          </td>
                          <td className="px-3 py-1.5 tabular-nums">
                            {p.enclosed_area_ha != null
                              ? formatNumber(p.enclosed_area_ha, 3)
                              : "—"}
                          </td>
                          <td className="px-3 py-1.5">{p.chainage}</td>
                          <td className="px-3 py-1.5">{p.product}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          ))}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/5 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-0.5 truncate text-sm font-semibold text-white">{value}</div>
    </div>
  );
}
