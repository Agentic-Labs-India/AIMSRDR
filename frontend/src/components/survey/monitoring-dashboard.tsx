"use client";

import {
  Activity,
  AlertTriangle,
  Box,
  Download,
  FileText,
  Layers3,
  Map as MapIcon,
  RefreshCw,
  Satellite,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  computeDisplacementScale,
  DemTerrainScene,
} from "@/components/survey/dem-terrain-scene";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  fetchComparison,
  fetchPatioVolumeReport,
  fetchProcessJob,
  fetchSite,
  getApiBase,
  mediaUrl,
  patioVolumePdfUrl,
  startProcessJob,
  type PatioVolumeReportBundle,
} from "@/lib/api";
import { formatDate, formatNumber } from "@/lib/format";
import type { Comparison, ProcessJobStatus, Site, Survey } from "@/lib/types";
import { cn } from "@/lib/utils";

type Mode = "inspect" | "compare";
type DemViewLayer = "rgb" | "elevation" | "hillshade" | "heightmap" | "ortho";
type Section = "dashboard" | "3d" | "dem" | "change" | "ortho" | "parameters";

const SECTION_IDS = new Set([
  "dashboard",
  "3d",
  "dem",
  "change",
  "ortho",
  "parameters",
]);

const NAV: { id: Section; label: string; href: string; icon: typeof Activity }[] = [
  { id: "dashboard", label: "Dashboard", href: "/monitor", icon: Activity },
  { id: "3d", label: "3D Point Cloud", href: "/monitor/3d", icon: Box },
  { id: "dem", label: "DEM / TIF", href: "/monitor/dem", icon: MapIcon },
  { id: "change", label: "Change Detection", href: "/monitor/change", icon: Layers3 },
  { id: "ortho", label: "Ortho Imagery", href: "/monitor/ortho", icon: Satellite },
  { id: "parameters", label: "Patio Volumes", href: "/monitor/parameters", icon: FileText },
];

function MetaCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-3 backdrop-blur">
      <div className="text-[11px] uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 text-lg font-semibold text-white tabular-nums">{value}</div>
      {hint ? <div className="mt-0.5 text-xs text-slate-400">{hint}</div> : null}
    </div>
  );
}

function DateSelect({
  label,
  value,
  surveys,
  onChange,
}: {
  label: string;
  value: string;
  surveys: Survey[];
  onChange: (id: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-slate-300">
      {label}
      <select
        className="h-9 min-w-[210px] rounded-lg border border-white/15 bg-slate-900 px-2 text-sm text-white"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {surveys.map((s) => (
          <option key={s.id} value={s.id}>
            {formatDate(s.date)} — {s.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function MonitoringDashboard({
  initialSite,
  initialSection = "dashboard",
}: {
  initialSite: Site;
  initialSection?: string;
}) {
  const primaryFrom = initialSite.primary_compare?.from_survey_id ?? "report-24-feb";
  const primaryTo = initialSite.primary_compare?.to_survey_id ?? "report-3rd-march";
  const section = (SECTION_IDS.has(initialSection) ? initialSection : "dashboard") as Section;
  const isRoad = initialSite.asset_type === "road";

  const [site, setSite] = useState(initialSite);
  const [mode, setMode] = useState<Mode>(section === "change" ? "compare" : "inspect");
  const [inspectId, setInspectId] = useState(primaryFrom);
  const [compareFrom, setCompareFrom] = useState(primaryFrom);
  const [compareTo, setCompareTo] = useState(primaryTo);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [patioReport, setPatioReport] = useState<PatioVolumeReportBundle | null>(null);
  const [patioBusy, setPatioBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [exaggeration, setExaggeration] = useState(3);
  const [demLayer, setDemLayer] = useState<DemViewLayer>("ortho");
  const [processJob, setProcessJob] = useState<ProcessJobStatus | null>(null);

  const surveys = useMemo(
    () => [...site.surveys].sort((a, b) => a.date.localeCompare(b.date)),
    [site.surveys],
  );
  const survey = surveys.find((s) => s.id === inspectId) ?? surveys[0];
  const fromSurvey = surveys.find((s) => s.id === compareFrom);
  const toSurvey = surveys.find((s) => s.id === compareTo);

  useEffect(() => {
    if (section === "change") setMode("compare");
    if (section === "parameters") setMode("inspect");
  }, [section]);

  useEffect(() => {
    if (mode !== "compare" && section !== "change") return;
    let cancelled = false;
    async function load() {
      try {
        const cmp = await fetchComparison(site.id, compareFrom, compareTo);
        if (!cancelled) setComparison(cmp);
      } catch (err) {
        if (!cancelled) {
          setComparison(null);
          setMessage(err instanceof Error ? err.message : "Compare failed");
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [mode, section, site.id, compareFrom, compareTo]);

  useEffect(() => {
    if (section !== "parameters" || !survey?.id) return;
    let cancelled = false;
    async function load() {
      setPatioBusy(true);
      try {
        const report = await fetchPatioVolumeReport(site.id, survey.id, false);
        if (!cancelled) {
          setPatioReport(report);
          setMessage(null);
        }
      } catch (err) {
        if (!cancelled) {
          setPatioReport(null);
          setMessage(err instanceof Error ? err.message : "Patio volume report failed");
        }
      } finally {
        if (!cancelled) setPatioBusy(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [section, site.id, survey?.id]);

  async function generatePatioPdf(force = true) {
    if (!survey?.id) return;
    setPatioBusy(true);
    setMessage("Generating patio volume PDF…");
    try {
      const report = await fetchPatioVolumeReport(site.id, survey.id, force);
      setPatioReport(report);
      setMessage(
        `Patio volume PDF ready · ${formatNumber(report.summary.total_volume_m3, 0)} m³ across ${report.summary.pile_count} piles`,
      );
      window.open(patioVolumePdfUrl(site.id, survey.id, false), "_blank");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "PDF generation failed");
    } finally {
      setPatioBusy(false);
    }
  }

  async function refresh() {
    setBusy(true);
    try {
      setSite(await fetchSite(site.id));
      setMessage("Site data refreshed");
    } finally {
      setBusy(false);
    }
  }

  async function reprocess() {
    setBusy(true);
    setMessage("Starting DEM/Ortho processing...");
    setProcessJob({
      job_id: "",
      site_id: site.id,
      status: "queued",
      progress: 0,
      step: "Starting…",
      messages: [],
      error: null,
      result: null,
    });
    try {
      const started = await startProcessJob(site.id);
      setProcessJob({
        job_id: started.job_id,
        site_id: started.site_id,
        status: started.status,
        progress: started.progress,
        step: started.step,
        messages: [],
        error: null,
        result: null,
      });

      // Poll until the background job finishes.
      let latest = await fetchProcessJob(site.id, started.job_id);
      setProcessJob(latest);
      while (latest.status === "queued" || latest.status === "running") {
        await new Promise((r) => setTimeout(r, 1000));
        latest = await fetchProcessJob(site.id, started.job_id);
        setProcessJob(latest);
        setMessage(`${latest.step} (${Math.round(latest.progress)}%)`);
      }

      if (latest.status === "failed") {
        throw new Error(latest.error || "Processing failed");
      }

      setSite(await fetchSite(site.id));
      setMessage("Processing complete");
      setProcessJob(latest);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Processing failed");
    } finally {
      setBusy(false);
    }
  }

  const rasters = survey?.rasters;
  const demPreview = mediaUrl(rasters?.dem_preview_url);
  const demRgb =
    mediaUrl(rasters?.dem_rgb_url) ||
    (survey?.id ? mediaUrl(`/api/v1/media/${site.id}/${survey.id}-dem-rgb.png`) : null) ||
    demPreview;
  const demRgbTif =
    mediaUrl(rasters?.dem_rgb_tif_url) ||
    (survey?.id ? mediaUrl(`/api/v1/media/${site.id}/${survey.id}-dem-rgb.tif`) : null);
  const demHeight = mediaUrl(rasters?.dem_heightmap_url);
  const demHill = mediaUrl(rasters?.dem_hillshade_url);
  const demScaled =
    mediaUrl(rasters?.dem_scaled_url) ||
    (survey?.id ? mediaUrl(`/api/v1/media/${site.id}/${survey.id}-dem-scaled.tif`) : null);
  const orthoPreview = mediaUrl(rasters?.ortho_preview_url);
  const dodPreview = mediaUrl(comparison?.dod?.preview_url);
  const dodStats = comparison?.dod?.stats;

  const elev = rasters?.dem_metadata?.elevation_stats as
    | { minimum?: number; maximum?: number; mean?: number }
    | undefined;
  const extent = rasters?.dem_metadata?.extent as
    | { min_x?: number; max_x?: number; min_y?: number; max_y?: number }
    | undefined;
  const groundWidthM =
    extent?.min_x != null && extent?.max_x != null ? Math.abs(extent.max_x - extent.min_x) : null;
  const groundHeightM =
    extent?.min_y != null && extent?.max_y != null ? Math.abs(extent.max_y - extent.min_y) : null;
  const displacementScale = computeDisplacementScale({
    elevMinM: elev?.minimum ?? survey?.summary.dem_min_m,
    elevMaxM: elev?.maximum ?? survey?.summary.dem_max_m,
    groundWidthM,
    groundHeightM,
    exaggeration,
  });
  const demViewSrc =
    demLayer === "ortho"
      ? orthoPreview || demRgb
      : demLayer === "rgb"
        ? demRgb
        : demLayer === "hillshade"
          ? demHill
          : demLayer === "heightmap"
            ? demHeight
            : demPreview;

  const showDashboard = section === "dashboard";
  const show3d = section === "dashboard" || section === "3d";
  const showChange = section === "dashboard" || section === "change";
  const showOrtho = section === "dashboard" || section === "ortho";
  const showDem = section === "dashboard" || section === "dem";
  const showParameters = section === "parameters";

  return (
    <div className="min-h-screen bg-[#0b1220] text-slate-100">
      <div className="flex min-h-screen">
        <aside className="hidden w-64 shrink-0 border-r border-white/10 bg-[#0a101c] p-4 lg:block">
          <div className="mb-6">
            <div className="text-xs uppercase tracking-[0.2em] text-sky-400">AIMS RDR</div>
            <h1 className="mt-1 text-lg font-semibold leading-tight">Monitoring System</h1>
            <p className="mt-1 text-xs text-slate-400">Drone DEM & Ortho periodic monitoring</p>
          </div>
          <nav className="space-y-1">
            {NAV.map((item) => {
              const Icon = item.icon;
              return (
                <Link
                  key={item.id}
                  href={item.href}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm transition",
                    section === item.id
                      ? "bg-sky-500/20 text-sky-200"
                      : "text-slate-300 hover:bg-white/5",
                  )}
                >
                  <Icon className="size-4" />
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <div className="mt-8 rounded-xl border border-white/10 bg-white/5 p-3 text-xs text-slate-300">
            <div className="mb-2 font-medium text-white">Data sources</div>
            <ul className="space-y-1.5">
              <li>✓ DEM GeoTIFF (+ TFW/PRJ)</li>
              <li>✓ Ortho ECW/EWW/PRJ</li>
              <li>✓ DEM of Difference</li>
              <li className="text-slate-500">○ LiDAR / IoT (later)</li>
            </ul>
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-4 py-3 sm:px-6">
            <div>
              <div className="text-sm font-semibold">{site.name}</div>
              <div className="text-xs text-slate-400">
                {site.country} · {site.crs} · API {getApiBase()}
              </div>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant={mode === "inspect" ? "default" : "outline"}
                  onClick={() => setMode("inspect")}
                >
                  Inspect date
                </Button>
                <Button
                  size="sm"
                  variant={mode === "compare" ? "default" : "outline"}
                  onClick={() => setMode("compare")}
                >
                  Compare dates
                </Button>
              </div>
              {mode === "inspect" ? (
                <DateSelect
                  label="Monitoring date"
                  value={survey?.id ?? ""}
                  surveys={surveys}
                  onChange={setInspectId}
                />
              ) : (
                <>
                  <DateSelect
                    label="From"
                    value={compareFrom}
                    surveys={surveys}
                    onChange={setCompareFrom}
                  />
                  <DateSelect
                    label="To"
                    value={compareTo}
                    surveys={surveys}
                    onChange={setCompareTo}
                  />
                </>
              )}
              <Button size="sm" variant="outline" disabled={busy} onClick={() => void refresh()}>
                <RefreshCw className="size-3.5" /> Refresh
              </Button>
              <Button size="sm" disabled={busy} onClick={() => void reprocess()}>
                Process DEM/Ortho
              </Button>
            </div>
          </header>

          {message || processJob ? (
            <div className="space-y-2 border-b border-sky-500/30 bg-sky-500/10 px-4 py-3 text-xs text-sky-50 sm:px-6">
              {message ? <div>{message}</div> : null}
              {processJob && (busy || processJob.status === "running" || processJob.status === "queued") ? (
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between gap-3 text-[11px] text-sky-100/90">
                    <span className="truncate">{processJob.step || "Processing…"}</span>
                    <span className="tabular-nums">{Math.round(processJob.progress)}%</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-black/30">
                    <div
                      className="h-full rounded-full bg-sky-400 transition-[width] duration-500 ease-out"
                      style={{ width: `${Math.max(2, Math.min(100, processJob.progress))}%` }}
                    />
                  </div>
                </div>
              ) : null}
              {processJob?.status === "completed" && !busy ? (
                <div className="h-2 overflow-hidden rounded-full bg-black/30">
                  <div className="h-full w-full rounded-full bg-emerald-400" />
                </div>
              ) : null}
              {processJob?.status === "failed" ? (
                <div className="text-amber-200">{processJob.error || "Processing failed"}</div>
              ) : null}
            </div>
          ) : null}

          <div className="space-y-4 p-4 sm:p-6">
            {(showDashboard || showParameters) && survey ? (
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
                <MetaCard label="Site / Project" value={site.name} hint={`${site.asset_type} · ${site.id}`} />
                <MetaCard
                  label="Inspection date"
                  value={formatDate(survey.date)}
                  hint={survey.label}
                />
                <MetaCard
                  label="DEM elevation"
                  value={
                    elev?.mean != null
                      ? `${formatNumber(elev.mean, 2)} m`
                      : survey.summary.dem_mean_m != null
                        ? `${formatNumber(survey.summary.dem_mean_m, 2)} m`
                        : "—"
                  }
                  hint={
                    elev?.minimum != null && elev?.maximum != null
                      ? `${formatNumber(elev.minimum, 1)} – ${formatNumber(elev.maximum, 1)} m`
                      : "Mean elevation"
                  }
                />
                <MetaCard
                  label="Coverage area"
                  value={
                    survey.summary.area_km2 != null
                      ? `${formatNumber(survey.summary.area_km2, 3)} km²`
                      : "—"
                  }
                  hint={
                    survey.summary.dem_width_px
                      ? `${survey.summary.dem_width_px}×${survey.summary.dem_height_px} px`
                      : "From DEM"
                  }
                />
                <MetaCard
                  label="GSD / resolution"
                  value={
                    survey.summary.gsd_cm != null
                      ? `${formatNumber(survey.summary.gsd_cm, 1)} cm`
                      : "—"
                  }
                  hint="DEM pixel size"
                />
                <MetaCard
                  label={isRoad ? "Surface depressions" : "Named piles"}
                  value={
                    survey.summary.named_pile_count != null
                      ? String(survey.summary.named_pile_count)
                      : survey.summary.pile_count != null
                        ? String(survey.summary.pile_count)
                        : dodStats?.pothole_candidates != null
                          ? String(dodStats.pothole_candidates)
                          : "—"
                  }
                  hint={
                    survey.summary.net_volume_m3 != null
                      ? `Net ${formatNumber(survey.summary.net_volume_m3, 0)} m³`
                      : "Patio stockpiles / DoD"
                  }
                />
              </div>
            ) : null}

            {showDashboard ? (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
                {NAV.filter((n) => n.id !== "dashboard").map((item) => {
                  const Icon = item.icon;
                  return (
                    <Link
                      key={item.id}
                      href={item.href}
                      className="rounded-xl border border-white/10 bg-white/5 px-4 py-4 transition hover:border-sky-400/40 hover:bg-sky-500/10"
                    >
                      <Icon className="mb-2 size-5 text-sky-300" />
                      <div className="font-medium text-white">{item.label}</div>
                      <div className="mt-1 text-xs text-slate-400">Open route →</div>
                    </Link>
                  );
                })}
              </div>
            ) : null}

            {(show3d || showChange || showOrtho) && (
            <div
              className={cn(
                "grid gap-4",
                show3d && (showChange || showOrtho)
                  ? "xl:grid-cols-[1.4fr_1fr]"
                  : "grid-cols-1",
              )}
            >
              {show3d ? (
              <Card
                id="dem-3d"
                className="overflow-hidden border-white/10 bg-[#0f172a] text-slate-100"
              >
                <CardHeader className="flex flex-row items-center justify-between space-y-0">
                  <div>
                    <CardTitle className="text-white">3D point cloud</CardTitle>
                    <CardDescription className="text-slate-400">
                      True-color ortho RGB on DEM heights (same imagery as QGIS). Change heatmap stays
                      in DoD only.
                    </CardDescription>
                  </div>
                  <Badge variant="secondary">Point cloud</Badge>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="flex flex-wrap items-center gap-3 text-xs text-slate-300">
                    <label className="flex min-w-[220px] flex-1 items-center gap-2">
                      <span className="shrink-0 text-slate-400">Vertical scale</span>
                      <input
                        type="range"
                        min={1}
                        max={8}
                        step={0.5}
                        value={exaggeration}
                        onChange={(e) => setExaggeration(Number(e.target.value))}
                        className="w-full accent-sky-400"
                      />
                      <span className="w-10 tabular-nums text-white">{exaggeration.toFixed(1)}×</span>
                    </label>
                    <span className="text-slate-500">
                      Elev{" "}
                      {elev?.minimum != null && elev?.maximum != null
                        ? `${formatNumber(elev.minimum, 1)}–${formatNumber(elev.maximum, 1)} m`
                        : "—"}
                      {groundWidthM != null && groundHeightM != null
                        ? ` · ground ${formatNumber(groundWidthM, 0)}×${formatNumber(groundHeightM, 0)} m`
                        : null}
                      {orthoPreview ? " · textured from ortho" : " · natural shade (ortho pending)"}
                    </span>
                  </div>
                  <div className="h-[460px]">
                    <DemTerrainScene
                      heightmapUrl={demHeight || ""}
                      textureUrl={orthoPreview}
                      hillshadeUrl={demHill}
                      displacementScale={displacementScale}
                      exaggerationLabel={`${exaggeration.toFixed(1)}× Z`}
                      mode="points"
                    />
                  </div>
                </CardContent>
              </Card>
              ) : null}

              {(showChange || showOrtho) ? (
              <div className="grid gap-4">
                {showChange ? (
                <Card className="border-white/10 bg-[#0f172a] text-slate-100">
                  <CardHeader className="flex flex-row items-center justify-between space-y-0">
                    <div>
                      <CardTitle className="text-white">Change detection (DoD)</CardTitle>
                      <CardDescription className="text-slate-400">
                        {fromSurvey && toSurvey
                          ? `RGB heatmap · ${formatDate(fromSurvey.date)} → ${formatDate(toSurvey.date)}`
                          : "RGB change heatmap — select Compare dates"}
                      </CardDescription>
                    </div>
                    <Badge variant="outline">Heatmap</Badge>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {dodPreview ? (
                      <>
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={dodPreview}
                          alt="DEM of Difference"
                          className="h-56 w-full rounded-lg object-cover"
                        />
                        <div className="grid grid-cols-2 gap-2 text-xs">
                          <MetaCard
                            label="Max fill"
                            value={
                              dodStats?.max_m != null
                                ? `+${formatNumber(dodStats.max_m, 2)} m`
                                : "—"
                            }
                          />
                          <MetaCard
                            label="Max cut"
                            value={
                              dodStats?.min_m != null
                                ? `${formatNumber(dodStats.min_m, 2)} m`
                                : "—"
                            }
                          />
                          <MetaCard
                            label="Fill vol (approx)"
                            value={
                              dodStats?.fill_volume_m3_approx != null
                                ? `${formatNumber(dodStats.fill_volume_m3_approx, 0)} m³`
                                : "—"
                            }
                          />
                          <MetaCard
                            label="Cut vol (approx)"
                            value={
                              dodStats?.cut_volume_m3_approx != null
                                ? `${formatNumber(dodStats.cut_volume_m3_approx, 0)} m³`
                                : "—"
                            }
                          />
                        </div>
                        <div className="flex items-center justify-between text-[11px] text-slate-400">
                          <span>Cut (−{dodStats?.limit_m ?? 0.5} m)</span>
                          <span className="h-2 w-40 rounded-full bg-gradient-to-r from-blue-500 via-white to-red-500" />
                          <span>Fill (+{dodStats?.limit_m ?? 0.5} m)</span>
                        </div>
                      </>
                    ) : (
                      <div className="flex h-56 items-center justify-center rounded-lg border border-dashed border-white/15 text-sm text-slate-400">
                        DoD preview pending — click Process DEM/Ortho
                      </div>
                    )}
                  </CardContent>
                </Card>
                ) : null}

                {showOrtho ? (
                <Card className="border-white/10 bg-[#0f172a] text-slate-100">
                  <CardHeader>
                    <CardTitle className="text-white">Ortho imagery</CardTitle>
                    <CardDescription className="text-slate-400">
                      True-color RGB from ECW (via QGIS convert) or GeoTIFF
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {orthoPreview ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={orthoPreview}
                        alt="Ortho preview"
                        className={cn(
                          "w-full rounded-lg object-contain bg-black/40",
                          section === "ortho" ? "max-h-[70vh]" : "h-44 object-cover",
                        )}
                      />
                    ) : (
                      <div className="flex h-44 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-white/15 p-4 text-center text-xs text-slate-400">
                        <AlertTriangle className="size-4 text-amber-300" />
                        {rasters?.ortho_note ||
                          "Ortho preview unavailable. Run scripts/convert_ortho_ecw.ps1 then Process DEM/Ortho."}
                      </div>
                    )}
                  </CardContent>
                </Card>
                ) : null}
              </div>
              ) : null}
            </div>
            )}

            {showDem ? (
            <Card
              id="dem-viewer"
              className="border-white/10 bg-[#0f172a] text-slate-100"
            >
              <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3 space-y-0">
                <div>
                  <CardTitle className="text-white">DEM / GeoTIFF viewer</CardTitle>
                  <CardDescription className="text-slate-400">
                    RGB terrain from the DEM TIF (color × hillshade), plus elevation / hillshade /
                    heightmap. Download the RGB GeoTIFF for GIS — raw multi‑GB TIF stays on the API.
                  </CardDescription>
                </div>
                <div className="flex flex-wrap gap-2">
                  {(
                    [
                      ["rgb", "RGB"],
                      ["elevation", "Elevation"],
                      ["hillshade", "Hillshade"],
                      ["heightmap", "Heightmap"],
                      ...(orthoPreview ? ([["ortho", "Ortho RGB"]] as const) : []),
                    ] as const
                  ).map(([id, label]) => (
                    <Button
                      key={id}
                      size="sm"
                      variant={demLayer === id ? "default" : "outline"}
                      onClick={() => setDemLayer(id)}
                    >
                      {label}
                    </Button>
                  ))}
                  {demRgbTif ? (
                    <a
                      href={`${demRgbTif}?download=true`}
                      download
                      className="inline-flex h-7 items-center gap-1 rounded-2xl border border-transparent bg-white px-3 text-sm font-medium text-black"
                    >
                      <Download className="size-3.5" /> RGB GeoTIFF
                    </a>
                  ) : null}
                  {demScaled ? (
                    <a
                      href={`${demScaled}?download=true`}
                      download
                      className="inline-flex h-7 items-center gap-1 rounded-2xl border border-white/20 bg-transparent px-3 text-sm font-medium text-slate-200"
                    >
                      <Download className="size-3.5" /> Elev GeoTIFF
                    </a>
                  ) : null}
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {demViewSrc ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={demViewSrc}
                    alt={`DEM ${demLayer}`}
                    className="max-h-[520px] w-full rounded-lg object-contain bg-black/40"
                  />
                ) : (
                  <div className="flex h-64 items-center justify-center rounded-lg border border-dashed border-white/15 text-sm text-slate-400">
                    DEM view pending — click Process DEM/Ortho
                  </div>
                )}
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 text-sm text-slate-300">
                  <div className="rounded-lg border border-white/10 bg-white/5 px-3 py-2">
                    <div className="text-[11px] uppercase text-slate-400">Source TIF</div>
                    <div className="mt-1 truncate text-xs">
                      {survey?.assets?.dtm?.path ??
                        (typeof rasters?.dem_metadata?.path === "string"
                          ? rasters.dem_metadata.path
                          : "—")}
                    </div>
                  </div>
                  <div className="rounded-lg border border-white/10 bg-white/5 px-3 py-2">
                    <div className="text-[11px] uppercase text-slate-400">Size</div>
                    <div className="mt-1 tabular-nums">
                      {survey?.assets?.dtm?.bytes != null
                        ? `${formatNumber(survey.assets.dtm.bytes / 1_000_000, 1)} MB`
                        : "—"}
                      {typeof rasters?.dem_metadata?.width_px === "number" &&
                      typeof rasters?.dem_metadata?.height_px === "number"
                        ? ` · ${rasters.dem_metadata.width_px}×${rasters.dem_metadata.height_px}`
                        : ""}
                    </div>
                  </div>
                  <div className="rounded-lg border border-white/10 bg-white/5 px-3 py-2">
                    <div className="text-[11px] uppercase text-slate-400">GSD / sidecars</div>
                    <div className="mt-1">
                      {survey?.summary.gsd_cm != null
                        ? `${formatNumber(survey.summary.gsd_cm, 1)} cm`
                        : "—"}
                      {" · "}
                      {(rasters?.dem_metadata?.sidecars as { tfw?: boolean; prj?: boolean } | undefined)
                        ?.tfw
                        ? "TFW ✓"
                        : "TFW ·"}{" "}
                      {(rasters?.dem_metadata?.sidecars as { tfw?: boolean; prj?: boolean } | undefined)
                        ?.prj
                        ? "PRJ ✓"
                        : "PRJ ·"}
                    </div>
                  </div>
                  <div className="rounded-lg border border-white/10 bg-white/5 px-3 py-2">
                    <div className="text-[11px] uppercase text-slate-400">Package / ortho</div>
                    <div className="mt-1 truncate text-xs">
                      {survey?.report_package ?? "—"}
                      {typeof rasters?.ortho_metadata?.gsd_cm === "number"
                        ? ` · ortho ${formatNumber(rasters.ortho_metadata.gsd_cm as number, 1)} cm`
                        : ""}
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
            ) : null}

            {showParameters ? (
              <div className="space-y-4">
                <Card className="border-white/10 bg-[#0f172a] text-slate-100">
                  <CardHeader className="flex flex-row items-start justify-between gap-3">
                    <div>
                      <CardTitle className="text-white">
                        Calculation of Loose Coal Volumes
                      </CardTitle>
                      <CardDescription className="text-slate-400">
                        Coal patio stockpiles (not road potholes). Named piles NC_CY*, product
                        class, chainage, height, angle of repose — MatrixGeo-style PDF.
                      </CardDescription>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      className="shrink-0 border-white/30 bg-transparent text-foreground hover:bg-white/10"
                      disabled={patioBusy || !survey?.id}
                      onClick={() => void generatePatioPdf(true)}
                    >
                      <Download className="mr-2 size-4" />
                      {patioBusy ? "Building…" : "Generate PDF"}
                    </Button>
                  </CardHeader>
                  <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    <MetaCard
                      label="Survey"
                      value={survey ? formatDate(survey.date) : "—"}
                      hint={patioReport?.summary.source_stage ?? survey?.id}
                    />
                    <MetaCard
                      label="Named piles"
                      value={String(patioReport?.summary.pile_count ?? "—")}
                    />
                    <MetaCard
                      label="Total net volume"
                      value={
                        patioReport?.summary.total_volume_m3 != null
                          ? `${formatNumber(patioReport.summary.total_volume_m3, 0)} m³`
                          : "—"
                      }
                    />
                    <MetaCard
                      label="Patio A / B / C"
                      value={
                        patioReport
                          ? `${formatNumber(patioReport.summary.totals_by_patio.A ?? 0, 0)} / ${formatNumber(patioReport.summary.totals_by_patio.B ?? 0, 0)} / ${formatNumber(patioReport.summary.totals_by_patio.C ?? 0, 0)}`
                          : "—"
                      }
                      hint="m³"
                    />
                  </CardContent>
                </Card>

                {patioReport
                  ? Object.entries(patioReport.data.patios)
                      .sort(([a], [b]) => a.localeCompare(b))
                      .map(([patio, block]) => (
                        <Card
                          key={patio}
                          className="border-white/10 bg-[#0f172a] text-slate-100"
                        >
                          <CardHeader>
                            <CardTitle className="text-white">
                              PATIO {patio} · {formatNumber(block.total_volume_m3, 2)} m³
                            </CardTitle>
                            <CardDescription className="text-slate-400">
                              {block.pile_count} piles · deep morphometric product classification
                            </CardDescription>
                          </CardHeader>
                          <CardContent>
                            <div className="overflow-x-auto rounded-lg border border-white/10">
                              <table className="min-w-full text-left text-xs text-slate-200">
                                <thead className="bg-white/5 text-[11px] uppercase tracking-wide text-slate-400">
                                  <tr>
                                    <th className="px-3 py-2">Pile</th>
                                    <th className="px-3 py-2">Date</th>
                                    <th className="px-3 py-2">Net Vol (m³)</th>
                                    <th className="px-3 py-2">Area (ha)</th>
                                    <th className="px-3 py-2">Chainage</th>
                                    <th className="px-3 py-2">Product</th>
                                    <th className="px-3 py-2">Max H (m)</th>
                                    <th className="px-3 py-2">Repose (°)</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {block.piles.map((p) => (
                                    <tr
                                      key={p.pile_name}
                                      className="border-t border-white/10"
                                    >
                                      <td className="px-3 py-2 font-mono text-[11px]">
                                        {p.pile_name}
                                      </td>
                                      <td className="px-3 py-2">{p.date_of_survey}</td>
                                      <td className="px-3 py-2 tabular-nums">
                                        {formatNumber(p.net_volume_m3, 2)}
                                      </td>
                                      <td className="px-3 py-2 tabular-nums">
                                        {p.enclosed_area_ha != null
                                          ? formatNumber(p.enclosed_area_ha, 3)
                                          : "—"}
                                      </td>
                                      <td className="px-3 py-2 tabular-nums">{p.chainage}</td>
                                      <td className="px-3 py-2">{p.product}</td>
                                      <td className="px-3 py-2 tabular-nums">
                                        {p.maximum_height_m != null
                                          ? formatNumber(p.maximum_height_m, 4)
                                          : "—"}
                                      </td>
                                      <td className="px-3 py-2 tabular-nums">
                                        {p.avg_angle_of_repose_deg != null
                                          ? formatNumber(p.avg_angle_of_repose_deg, 2)
                                          : "—"}
                                      </td>
                                    </tr>
                                  ))}
                                  <tr className="border-t border-white/20 bg-white/5 font-semibold">
                                    <td className="px-3 py-2" colSpan={2}>
                                      Total Volume
                                    </td>
                                    <td className="px-3 py-2 tabular-nums">
                                      {formatNumber(block.total_volume_m3, 2)}
                                    </td>
                                    <td className="px-3 py-2" colSpan={5} />
                                  </tr>
                                </tbody>
                              </table>
                            </div>
                          </CardContent>
                        </Card>
                      ))
                  : (
                    <Card className="border-white/10 bg-[#0f172a] text-slate-100">
                      <CardContent className="py-8 text-sm text-slate-400">
                        {patioBusy
                          ? "Loading patio volume classification…"
                          : "No patio volume data yet. Ensure stage pile polygons and volume JSON exist under processed/."}
                      </CardContent>
                    </Card>
                  )}
              </div>
            ) : null}

            {showChange && comparison ? (
              <Card className="border-white/10 bg-[#0f172a] text-slate-100">
                <CardHeader>
                  <CardTitle className="text-white">Comparison notes</CardTitle>
                </CardHeader>
                <CardContent>
                  <ul className="list-disc space-y-1 ps-5 text-sm text-slate-300">
                    {comparison.notes.map((note) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
