import { MonitoringDashboard } from "@/components/survey/monitoring-dashboard";
import { fetchSite } from "@/lib/api";

export const dynamic = "force-dynamic";

const SECTIONS = new Set(["dashboard", "3d", "dem", "change", "ortho", "parameters"]);

export default async function MonitorPage({
  params,
}: {
  params: Promise<{ slug?: string[] }>;
}) {
  const { slug } = await params;
  const section = slug?.[0] && SECTIONS.has(slug[0]) ? slug[0] : "dashboard";

  try {
    const site = await fetchSite("nacala-coal-field");
    return (
      <main className="min-h-screen bg-[#0b1220]">
        <MonitoringDashboard initialSite={site} initialSection={section} />
      </main>
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown API error";
    return (
      <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-4 px-6">
        <h1 className="text-2xl font-semibold">Backend unavailable</h1>
        <p className="text-sm leading-6 text-muted-foreground">
          Start the FastAPI service (Docker or local uvicorn) on{" "}
          <code className="rounded bg-muted px-1.5 py-0.5">http://localhost:8000</code>, then refresh.
        </p>
        <pre className="overflow-x-auto rounded-xl border bg-card p-4 text-xs text-destructive">
          {message}
        </pre>
      </main>
    );
  }
}
