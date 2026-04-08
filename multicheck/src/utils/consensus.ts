import type { SignalVote } from "../types/multicheck.js";
import type { GeoSignals } from "../types/signals.js";
import { CONFIG } from "../config.js";

// Field-field yang penting untuk di-vote (field infrastruktur tidak divote, terlalu noise)
export const VOTABLE_FIELDS: (keyof GeoSignals)[] = [
  "plate_prefix",
  "plate_region",
  "street_name",
  "cross_street",
  "junction_name",
  "area_name",
  "city_district",
  "province",
  "landmark_sign",
  "landmark_type",
  "waterway_name",
  "road_type",
  "road_lanes",
  "transjakarta_corridor",
  "transjakarta_halte",
];

// Voting untuk satu field dari N runs
export function voteOnField(
  field:  keyof GeoSignals,
  values: unknown[],           // satu value per run
): SignalVote {
  // Normalisasi value: string lowercase, null tetap null
  const normalized = values.map(v =>
    typeof v === "string" ? v.toLowerCase().trim() : v
  );

  // Hitung frekuensi tiap value
  const freq = new Map<string, number>();
  for (const v of normalized) {
    const key = JSON.stringify(v);   // null → "null", string → string dengan quotes
    freq.set(key, (freq.get(key) ?? 0) + 1);
  }

  // Cari value dengan frekuensi tertinggi
  let topKey   = "null";
  let topCount = 0;
  for (const [k, c] of freq) {
    if (c > topCount) { topCount = c; topKey = k; }
  }

  const agreedValue   = JSON.parse(topKey);
  const passed        = topCount >= CONFIG.CP1_MIN_AGREEMENT;
  const confidenceMult = passed
    ? (topCount === values.length ? 1.0 : 0.8)   // semua agree = 1.0, partial = 0.8
    : CONFIG.CP1_VARIANCE_PENALTY;

  return {
    field:          field as string,
    values:         normalized,
    agreedValue:    passed ? agreedValue : undefined,
    agreementCount: topCount,
    passed,
    confidenceMult,
  };
}

// Build consensus signals dari hasil voting
export function buildConsensusSignals(
  votes:       SignalVote[],
  baseSignals: Partial<GeoSignals>,   // fallback dari original extraction
): Partial<GeoSignals> {
  const result: Partial<GeoSignals> = { ...baseSignals };

  for (const vote of votes) {
    const field = vote.field as keyof GeoSignals;
    if (vote.passed && vote.agreedValue !== undefined) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (result as any)[field] = vote.agreedValue;
    } else if (!vote.passed) {
      // Sinyal tidak konsisten → set ke null untuk menghindari confident wrongness
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (result as any)[field] = null;
    }
  }

  return result;
}
