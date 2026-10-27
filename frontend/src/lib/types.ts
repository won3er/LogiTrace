import { z } from "zod";

export const FacilitySchema = z.object({
  id: z.number(),
  external_id: z.string(),
  record_class: z.enum(["official", "user", "synthetic"]),
  name: z.string(),
  category: z.string(),
  category_label: z.string(),
  subcategory: z.string().nullable(),
  modal: z.string(),
  operator: z.string().nullable(),
  capacity_value: z.number().nullable(),
  capacity_unit: z.string().nullable(),
  status: z.string().nullable(),
  address: z.string().nullable(),
  municipality_code: z.number().nullable(),
  municipality_name: z.string().nullable(),
  uf: z.string().nullable(),
  lon: z.number(),
  lat: z.number(),
  reliability: z.string(),
  limitations: z.string().nullable(),
  source_key: z.string().nullable(),
  source_name: z.string().nullable(),
  source_reference: z.string().nullable(),
  attributes: z.record(z.string(), z.unknown()),
  updated_at: z.string(),
});
export type Facility = z.infer<typeof FacilitySchema>;

export const pageOf = <T extends z.ZodTypeAny>(item: T) =>
  z.object({ items: z.array(item), total: z.number(), page: z.number(), page_size: z.number() });

export const MetricSchema = z.object({
  key: z.string(),
  label: z.string(),
  value: z.number().nullable(),
  unit: z.string(),
  definition: z.string(),
  period: z.string(),
  source: z.string(),
  denominator: z.string().nullable().optional(),
  limitations: z.string().nullable().optional(),
});
export type Metric = z.infer<typeof MetricSchema>;

export const JobSchema = z.object({
  id: z.number(),
  kind: z.string(),
  status: z.enum(["queued", "running", "success", "failed"]),
  progress: z.number(),
  message: z.string().nullable(),
  ref_type: z.string().nullable(),
  ref_id: z.number().nullable(),
  error: z.string().nullable(),
});
export type Job = z.infer<typeof JobSchema>;

export const PathSummarySchema = z.object({
  distance_km: z.number(),
  time_h: z.number(),
  cost_brl_t: z.number(),
  km_by_modal: z.record(z.string(), z.number()),
  transfers: z.number(),
  edge_count: z.number(),
});

export const RouteSchema = PathSummarySchema.extend({
  rank: z.number(),
  roads: z.array(z.string()),
  geojson: z.object({ type: z.literal("FeatureCollection"), features: z.array(z.any()) }),
  edges: z.array(z.number()),
  overlap_with_best: z.number().optional(),
  delta_vs_best: z.object({ distance_km: z.number(), time_h: z.number(), cost_brl_t: z.number() }).optional(),
});
export type Route = z.infer<typeof RouteSchema>;

export const RouteResponseSchema = z.object({
  connected: z.boolean(),
  origin: z.string(),
  dest: z.string(),
  straight_km: z.number(),
  metric: z.string().optional(),
  metric_unit: z.string().optional(),
  mode: z.string().optional(),
  network_version_id: z.number().optional(),
  detour_index: z.number().nullable().optional(),
  snap_km: z.number().optional(),
  closed_edges: z.number().optional(),
  routes: z.array(RouteSchema),
  notes: z.array(z.string()).optional(),
  message: z.string().optional(),
  assumptions_used: z.record(z.string(), z.number()).optional(),
});
export type RouteResponse = z.infer<typeof RouteResponseSchema>;

export type Endpoint =
  | { type: "municipality"; id: number; label?: string }
  | { type: "facility"; id: number; label?: string }
  | { type: "point"; lon: number; lat: number; label?: string };

export type MunicipalityHit = { code: number; name: string; uf: string; population: number | null; lon: number; lat: number };

export type MetricMeta = { label: string; unit: string; period: string; source: string; definition: string; denominator?: string; limitations?: string };
