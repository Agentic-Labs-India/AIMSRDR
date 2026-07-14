import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export default function ApproachPage() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-6 py-10">
      <Link href="/" className={cn(buttonVariants({ variant: "outline" }), "w-fit")}>
        ← Monitoring
      </Link>
      <div className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">Implementation approach</h1>
        <p className="text-sm leading-6 text-muted-foreground">
          Full architecture and runbooks live in the repository root README. This page is the short
          product summary.
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Separation of concerns</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm leading-6 text-muted-foreground">
          <p>
            Next.js never loads multi-GB TIF/ECW/LAS files. The Dockerized FastAPI backend inventories
            the keep-set, converts shapefiles to GeoJSON, parses volume CSV, and emits a stable JSON
            contract.
          </p>
          <p>
            The frontend consumes that JSON for KPIs, plan overlays, comparison tables, and React
            Three Fiber extrusion of pile polygons. DTM meshes and ortho tiles are registered as
            pending worker outputs so the contract already supports them.
          </p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Current keep-set</CardTitle>
        </CardHeader>
        <CardContent className="text-sm leading-6 text-muted-foreground">
          Per survey stage: DTM + pile polygons (+ ortho when complete) + volumes when CSV exists.
          Site-level: patio limits and chainage. Duplicate March report folder and delivery junk are
          ignored by the catalog.
        </CardContent>
      </Card>
    </main>
  );
}
