import { z } from "zod";

const EnvSchema = z.object({
  OPENAI_API_KEY:      z.string().min(1),
  MAPBOX_ACCESS_TOKEN: z.string().min(1),
});

// Validate env at startup — fails fast dengan pesan jelas kalau key kurang
export const env = EnvSchema.parse(process.env);

export const CONFIG = {
  // Models — semua OpenAI
  VISION_MODEL:    "gpt-4.1-nano",   // harus sama dengan app.py (vision extraction)
  REASONING_MODEL: "gpt-4o-mini",    // untuk CP2 coherence + CP3 reverify (JSON reasoning)

  // Checkpoint 1 — Signal Consensus
  CP1_RUN_COUNT:        3,           // berapa kali extraction diulang
  CP1_MIN_AGREEMENT:    2,           // minimal runs yang harus sepakat
  CP1_VARIANCE_PENALTY: 0.3,         // weight multiplier untuk sinyal high-variance
  CP1_TIMEOUT_MS:       45_000,

  // Checkpoint 2 — Geographic Coherence
  CP2_BBOX_TOLERANCE_DEG:   0.05,   // derajat toleransi untuk plate-region bbox check
  CP2_MAPBOX_STREET_LIMIT:  3,      // max geocoding results untuk validasi street name
  CP2_MIN_COHERENT_SIGNALS: 2,      // minimum sinyal yang harus konsisten
  CP2_TIMEOUT_MS:           20_000,

  // Checkpoint 3 — Coordinate Reverse-Verification
  CP3_REVERIFY_RADIUS_M: 150,       // radius Mapbox tilequery (meter)
  CP3_TEMP:              0,         // temperature 0 = deterministic untuk verifikasi
  CP3_TIMEOUT_MS:        30_000,

  // Checkpoint 4 — Confidence Gate
  CP4_MIN_CHECKPOINTS_PASSED: 2,    // minimum dari 3 checkpoints untuk PROCEED
  CP4_HIGH_RISK_THRESHOLD:    0.6,  // hallucinationScore > ini = HIGH RISK

  // Retry
  RETRY_MAX_ATTEMPTS:  3,
  RETRY_BASE_DELAY_MS: 1_000,
  RETRY_MAX_DELAY_MS:  10_000,

  // I/O (dari CLI args)
  INPUT_PATH:  process.argv[2] ?? "",
  OUTPUT_PATH: process.argv[3] ?? "",
} as const;
