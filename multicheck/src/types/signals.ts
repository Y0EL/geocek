// Mirror exact shape dari geo_signals yang di-emit app.py
export interface GeoSignals {
  plate_prefix:          string | null;
  plate_region:          string | null;
  street_name:           string | null;
  cross_street:          string | null;
  junction_name:         string | null;
  area_name:             string | null;
  city_district:         string | null;
  province:              string | null;
  landmark_sign:         string | null;
  landmark_type:         string | null;
  water_body_visible:    boolean;
  waterway_name:         string | null;
  waterway_type:         string | null;
  road_type:             string | null;
  road_lanes:            number | null;
  road_lanes_direction:  number | null;
  median_present:        boolean;
  median_type:           string | null;
  traffic_light_present: boolean;
  sidewalk_present:      boolean;
  infrastructure_type:   string | null;
  camera_heading:        string | null;
  shadow_direction:      string | null;
  time_of_day:           string | null;
  visible_texts:         string[];
  poi_list:              string[];
  transjakarta_corridor: string | null;
  transjakarta_halte:    string | null;
  bus_stop_visible:      boolean;
  vegetation_type:       string | null;
  commercial_density:    string | null;
  area_type:             string | null;
}

// Full payload yang Python tulis ke disk (+ pass-through section lain)
export interface PipelineInput {
  geo_signals:  GeoSignals;
  image_path?:  string;           // path ke gambar (dibutuhkan CP1 untuk re-run)
  [key: string]: unknown;
}
