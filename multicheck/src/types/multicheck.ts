import type { GeoSignals, PipelineInput } from "./signals.js";
import type { PipelineCandidate } from "./candidates.js";

// ─── Checkpoint 1: Signal Consensus ──────────────────────────────────────────

export interface ExtractionRun {
  runIndex:   number;
  signals:    Partial<GeoSignals>;
  durationMs: number;
}

export interface SignalVote {
  field:          string;
  values:         unknown[];         // satu value per run
  agreedValue:    unknown;           // value yang menang (undefined jika tidak ada majority)
  agreementCount: number;
  passed:         boolean;           // >= CP1_MIN_AGREEMENT
  confidenceMult: number;            // 1.0 jika semua agree, CP1_VARIANCE_PENALTY jika tidak
}

export interface CP1Result {
  passed:           boolean;
  runs:             ExtractionRun[];
  votes:            SignalVote[];
  consensusSignals: Partial<GeoSignals>;   // hanya field yang agreed
  rejectedFields:   string[];
  durationMs:       number;
}

// ─── Checkpoint 2: Geographic Coherence ──────────────────────────────────────

export type CoherenceIssueKind =
  | "PLATE_BBOX_MISMATCH"
  | "STREET_NOT_FOUND_IN_REGION"
  | "SIGNALS_POINT_TO_DIFFERENT_AREAS"
  | "PROVINCE_CITY_MISMATCH";

export interface CoherenceIssue {
  kind:     CoherenceIssueKind;
  signal:   string;
  detail:   string;
  severity: "HARD" | "SOFT";   // HARD = hapus sinyal; SOFT = kurangi weight
}

export interface CP2Result {
  passed:          boolean;
  coherentSignals: string[];
  flaggedSignals:  string[];
  issues:          CoherenceIssue[];
  adjustedWeights: Record<string, number>;   // field → multiplier (0.0–1.0)
  durationMs:      number;
}

// ─── Checkpoint 3: Coordinate Reverse-Verification ───────────────────────────

export interface ReverseVerification {
  candidateName:    string;
  lat:              number;
  lon:              number;
  mapboxRoadsFound: string[];
  mapboxPoisFound:  string[];
  claudeVerdict:    "CONSISTENT" | "INCONSISTENT" | "UNCERTAIN";
  claudeReasoning:  string;
  scoreMult:        number;           // 1.0 CONSISTENT, 0.5 UNCERTAIN, 0.3 INCONSISTENT
  passed:           boolean;
}

export interface CP3Result {
  passed:        boolean;
  verifications: ReverseVerification[];
  durationMs:    number;
}

// ─── Checkpoint 4: Confidence Gate ───────────────────────────────────────────

export type HallucinationRisk = "LOW" | "MEDIUM" | "HIGH";

export interface CP4Result {
  passed:               boolean;
  checkpointsPassed:    number;        // 0–3
  hallucinationRisk:    HallucinationRisk;
  hallucinationScore:   number;        // 0.0 bersih, 1.0 penuh halusinasi
  consistentSignals:    string[];
  contradictorySignals: string[];
  recommendation:       "PROCEED" | "PROCEED_WITH_CAUTION" | "REJECT";
}

// ─── Full Multicheck Report ───────────────────────────────────────────────────

export interface MulticheckReport {
  multicheckVersion:  string;
  timestampMs:        number;
  cp1:                CP1Result;
  cp2:                CP2Result;
  cp3:                CP3Result | null;   // null jika belum ada candidates
  cp4:                CP4Result;
  verifiedGeoSignals: Partial<GeoSignals>;   // menggantikan geo_signals raw
  candidateMultipliers: Record<string, number>;   // candidate name → score multiplier dari CP3
  totalDurationMs:    number;
}

// Output JSON yang ditulis kembali ke disk
export interface AugmentedPipelineInput extends PipelineInput {
  geo_signals: GeoSignals;
  multicheck:  MulticheckReport;
}

// Untuk passing candidates ke CP3 (dibaca dari result.geojson kalau sudah ada)
export interface CandidatesInput {
  candidates: PipelineCandidate[];
}
