export type AssetStatus = "available" | "missing" | "pending" | "processed";

export type AssetRef = {
  kind: string;
  status: AssetStatus;
  path: string | null;
  url: string | null;
  bytes: number | null;
  note: string | null;
};

export type PileMetrics = {
  id: string;
  patio: string | null;
  name: string | null;
  total_volume_m3: number | null;
  net_volume_m3: number | null;
  cut_volume_m3: number | null;
  fill_volume_m3: number | null;
  enclosed_area_ha: number | null;
  perimeter_m: number | null;
  avg_elev_m: number | null;
  min_elev_m: number | null;
  max_elev_m: number | null;
  centroid: [number, number] | null;
  properties: Record<string, unknown>;
};

export type SurveySummary = {
  net_volume_m3: number | null;
  total_volume_m3: number | null;
  cut_volume_m3: number | null;
  fill_volume_m3: number | null;
  enclosed_area_ha: number | null;
  perimeter_km: number | null;
  pile_count: number;
  named_pile_count: number;
  dem_min_m: number | null;
  dem_max_m: number | null;
  dem_mean_m: number | null;
  area_km2: number | null;
  gsd_cm: number | null;
  dem_width_px: number | null;
  dem_height_px: number | null;
};

export type RasterProducts = {
  dem_preview_url: string | null;
  dem_rgb_url?: string | null;
  dem_rgb_tif_url?: string | null;
  dem_heightmap_url: string | null;
  dem_hillshade_url: string | null;
  dem_scaled_url?: string | null;
  dem_meta_url: string | null;
  ortho_preview_url: string | null;
  ortho_meta_url: string | null;
  ortho_status: string | null;
  ortho_note: string | null;
  dem_metadata: Record<string, unknown>;
  ortho_metadata: Record<string, unknown>;
};

export type Survey = {
  id: string;
  label: string;
  date: string;
  stage: number;
  crs: string;
  report_package: string | null;
  is_primary: boolean;
  assets: Record<string, AssetRef>;
  summary: SurveySummary;
  piles: PileMetrics[];
  piles_geojson_url: string | null;
  rasters?: RasterProducts | null;
};

export type PrimaryCompare = {
  from_survey_id: string;
  to_survey_id: string;
  label: string;
};

export type Site = {
  id: string;
  name: string;
  asset_type: string;
  crs: string;
  country: string;
  description: string;
  patio_geojson_url: string | null;
  chainage_geojson_url: string | null;
  primary_compare: PrimaryCompare | null;
  surveys: Survey[];
};

export type PileDelta = {
  id: string;
  patio: string | null;
  volume_from_m3: number | null;
  volume_to_m3: number | null;
  delta_m3: number | null;
  area_from_ha: number | null;
  area_to_ha: number | null;
  delta_area_ha: number | null;
  centroid: [number, number] | null;
};

export type ProcessJobStart = {
  job_id: string;
  site_id: string;
  status: string;
  progress: number;
  step: string;
};

export type ProcessJobStatus = {
  job_id: string;
  site_id: string;
  status: "queued" | "running" | "completed" | "failed" | string;
  progress: number;
  step: string;
  messages: string[];
  error: string | null;
  result: Record<string, unknown> | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type SurfaceDefect = {
  id: string;
  type: "pothole" | "rut" | "heave" | string;
  severity: string;
  depth_m?: number | null;
  delta_m?: number | null;
  area_m2_approx?: number | null;
  pixel?: number[] | null;
  easting?: number | null;
  northing?: number | null;
};

export type DodProducts = {
  preview_url: string | null;
  stats_url: string | null;
  defects_url?: string | null;
  stats: {
    min_m?: number | null;
    max_m?: number | null;
    mean_m?: number | null;
    std_m?: number | null;
    abs_mean_m?: number | null;
    p2_m?: number | null;
    p98_m?: number | null;
    cut_share?: number | null;
    fill_share?: number | null;
    cut_volume_m3_approx?: number | null;
    fill_volume_m3_approx?: number | null;
    net_volume_m3_approx?: number | null;
    sample_pixels?: number | null;
    pixel_area_m2?: number | null;
    limit_m?: number | null;
    pothole_candidates?: number | null;
    heave_candidates?: number | null;
    rut_candidates?: number | null;
    max_pothole_depth_m?: number | null;
    mean_pothole_depth_m?: number | null;
  };
  defects?: {
    summary?: {
      pothole_candidates?: number;
      rut_candidates?: number;
      heave_candidates?: number;
      total_candidates?: number;
      max_pothole_depth_m?: number | null;
      mean_pothole_depth_m?: number | null;
      depression_threshold_m?: number;
      heave_threshold_m?: number;
    };
    features?: SurfaceDefect[];
  };
};

export type Comparison = {
  site_id: string;
  from_survey_id: string;
  to_survey_id: string;
  cut_volume_m3: number | null;
  fill_volume_m3: number | null;
  net_delta_m3: number | null;
  matched_piles: number;
  unmatched_from: string[];
  unmatched_to: string[];
  piles: PileDelta[];
  notes: string[];
  dod: DodProducts;
};

export type GeoJSONFeatureCollection = {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    id?: string | number;
    properties: Record<string, unknown>;
    geometry: {
      type: string;
      coordinates: unknown;
    };
  }>;
};
