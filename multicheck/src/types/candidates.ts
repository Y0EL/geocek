// Mirror shape dari tiap feature di result.geojson yang dihasilkan Python
export interface PipelineCandidate {
  lat:              number;
  lon:              number;
  name:             string;
  confidence_score: number;
  confidence_label: string;
  radius_m:         number;
  matched_signals:  string[];
  ai_reasoning:     string;
}
