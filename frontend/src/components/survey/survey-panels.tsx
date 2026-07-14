import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatArea, formatBytes, formatDate, formatVolume } from "@/lib/format";
import type { AssetRef, Survey } from "@/lib/types";

function statusVariant(status: AssetRef["status"]) {
  if (status === "processed") return "success" as const;
  if (status === "available") return "secondary" as const;
  if (status === "pending") return "warning" as const;
  return "muted" as const;
}

export function KpiGrid({ survey }: { survey: Survey }) {
  const items = [
    { label: "Net volume", value: formatVolume(survey.summary.net_volume_m3) },
    { label: "Total volume", value: formatVolume(survey.summary.total_volume_m3) },
    { label: "Enclosed area", value: formatArea(survey.summary.enclosed_area_ha) },
    { label: "Piles", value: String(survey.summary.pile_count) },
  ];
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => (
        <Card key={item.label} className="bg-background/70">
          <CardHeader className="pb-2">
            <CardDescription>{item.label}</CardDescription>
            <CardTitle className="text-2xl tabular-nums">{item.value}</CardTitle>
          </CardHeader>
        </Card>
      ))}
    </div>
  );
}

export function AssetStatusList({ assets }: { assets: Record<string, AssetRef> }) {
  return (
    <div className="grid gap-2">
      {Object.entries(assets).map(([key, asset]) => (
        <div
          key={key}
          className="flex items-start justify-between gap-3 rounded-xl border border-border/70 bg-background/50 px-3 py-2"
        >
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium capitalize">{key}</span>
              <Badge variant={statusVariant(asset.status)}>{asset.status}</Badge>
            </div>
            <p className="truncate text-xs text-muted-foreground">
              {asset.note ?? asset.path ?? "—"}
            </p>
          </div>
          <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{formatBytes(asset.bytes)}</span>
        </div>
      ))}
    </div>
  );
}

export function SurveyMeta({ survey }: { survey: Survey }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
      <Badge variant="outline">Inspection {formatDate(survey.date)}</Badge>
      <span>{survey.label}</span>
      <span>·</span>
      <span>{survey.crs}</span>
      <span>·</span>
      <span>{survey.summary.named_pile_count} named piles</span>
      {survey.report_package ? (
        <>
          <span>·</span>
          <span className="truncate">{survey.report_package}</span>
        </>
      ) : null}
    </div>
  );
}

export function PileTable({ survey }: { survey: Survey }) {
  const rows = [...survey.piles]
    .sort((a, b) => (b.net_volume_m3 ?? b.total_volume_m3 ?? 0) - (a.net_volume_m3 ?? a.total_volume_m3 ?? 0))
    .slice(0, 40);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Stockpiles</CardTitle>
        <CardDescription>
          Metrics from processed GeoJSON and volume CSV where available.
        </CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-sm">
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th className="py-2 pe-3 font-medium">ID</th>
              <th className="py-2 pe-3 font-medium">Patio</th>
              <th className="py-2 pe-3 font-medium">Net m³</th>
              <th className="py-2 pe-3 font-medium">Cut m³</th>
              <th className="py-2 pe-3 font-medium">Fill m³</th>
              <th className="py-2 font-medium">Area ha</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((pile) => (
              <tr key={pile.id} className="border-b border-border/60">
                <td className="py-2 pe-3 font-medium">{pile.name ?? pile.id}</td>
                <td className="py-2 pe-3">{pile.patio ?? "—"}</td>
                <td className="py-2 pe-3 tabular-nums">{formatVolume(pile.net_volume_m3 ?? pile.total_volume_m3)}</td>
                <td className="py-2 pe-3 tabular-nums">{formatVolume(pile.cut_volume_m3)}</td>
                <td className="py-2 pe-3 tabular-nums">{formatVolume(pile.fill_volume_m3)}</td>
                <td className="py-2 tabular-nums">{formatArea(pile.enclosed_area_ha)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
