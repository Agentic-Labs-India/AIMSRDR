import type {
  Comparison,
  GeoJSONFeatureCollection,
  ProcessJobStart,
  ProcessJobStatus,
  Site,
  Survey,
} from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export function getApiBase() {
  return API_BASE;
}

export function mediaUrl(path: string | null | undefined) {
  if (!path) return null;
  if (path.startsWith("http")) return path;
  return `${API_BASE}${path}`;
}

export async function fetchSite(siteId = "nacala-coal-field") {
  return apiFetch<Site>(`/api/v1/sites/${siteId}`);
}

export async function fetchSurvey(siteId: string, surveyId: string) {
  return apiFetch<Survey>(`/api/v1/sites/${siteId}/surveys/${surveyId}`);
}

export async function fetchComparison(siteId: string, fromId: string, toId: string) {
  const qs = new URLSearchParams({ from: fromId, to: toId });
  return apiFetch<Comparison>(`/api/v1/sites/${siteId}/compare?${qs}`);
}

export async function fetchGeoJSON(url: string) {
  const absolute = mediaUrl(url);
  if (!absolute) throw new Error("Missing GeoJSON URL");
  const res = await fetch(absolute, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to load GeoJSON (${res.status})`);
  return res.json() as Promise<GeoJSONFeatureCollection>;
}

export async function startProcessJob(siteId = "nacala-coal-field") {
  return apiFetch<ProcessJobStart>(`/api/v1/sites/${siteId}/process?async=true`, {
    method: "POST",
  });
}

export async function fetchProcessJob(siteId: string, jobId: string) {
  return apiFetch<ProcessJobStatus>(`/api/v1/sites/${siteId}/process/${jobId}`);
}

/** @deprecated Prefer startProcessJob + fetchProcessJob for progress UI. */
export async function reprocessSite(siteId = "nacala-coal-field") {
  return startProcessJob(siteId);
}
