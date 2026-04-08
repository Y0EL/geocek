import { z } from "zod";

export const GeoSignalsSchema = z.object({
  plate_prefix:          z.string().nullable().default(null),
  plate_region:          z.string().nullable().default(null),
  street_name:           z.string().nullable().default(null),
  cross_street:          z.string().nullable().default(null),
  junction_name:         z.string().nullable().default(null),
  area_name:             z.string().nullable().default(null),
  city_district:         z.string().nullable().default(null),
  province:              z.string().nullable().default(null),
  landmark_sign:         z.string().nullable().default(null),
  landmark_type:         z.string().nullable().default(null),
  water_body_visible:    z.boolean().default(false),
  waterway_name:         z.string().nullable().default(null),
  waterway_type:         z.string().nullable().default(null),
  road_type:             z.string().nullable().default(null),
  road_lanes:            z.number().int().nullable().default(null),
  road_lanes_direction:  z.number().int().nullable().default(null),
  median_present:        z.boolean().default(false),
  median_type:           z.string().nullable().default(null),
  traffic_light_present: z.boolean().default(false),
  sidewalk_present:      z.boolean().default(false),
  infrastructure_type:   z.string().nullable().default(null),
  camera_heading:        z.string().nullable().default(null),
  shadow_direction:      z.string().nullable().default(null),
  time_of_day:           z.string().nullable().default(null),
  visible_texts:         z.array(z.string()).default([]),
  poi_list:              z.array(z.string()).default([]),
  transjakarta_corridor: z.string().nullable().default(null),
  transjakarta_halte:    z.string().nullable().default(null),
  bus_stop_visible:      z.boolean().default(false),
  vegetation_type:       z.string().nullable().default(null),
  commercial_density:    z.string().nullable().default(null),
  area_type:             z.string().nullable().default(null),
});

// Input JSON dari Python (field lain di-passthrough)
export const PipelineInputSchema = z.object({
  geo_signals: GeoSignalsSchema,
  image_path:  z.string().optional(),
}).passthrough();

export type ValidatedGeoSignals = z.infer<typeof GeoSignalsSchema>;
