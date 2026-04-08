// Multicheck CLI Entry Point
// Usage: bun run src/index.ts <input_signals.json> <output_verified.json> [candidates.geojson]
//
// input_signals.json  : JSON dari Python (geo_signals + image_path + rest of pipeline input)
// output_verified.json: JSON augmented dengan field "multicheck" + verified geo_signals
// candidates.geojson  : (optional) result.geojson dari main.py untuk CP3

import { readFileSync, writeFileSync, existsSync } from "fs";
import { PipelineInputSchema } from "./schemas/signalSchema.js";
import { runCP1 } from "./checkpoints/cp1-signal-consensus.js";
import { runCP2 } from "./checkpoints/cp2-geographic-coherence.js";
import { runCP3 } from "./checkpoints/cp3-coordinate-reverify.js";
import { runCP4 } from "./checkpoints/cp4-confidence-gate.js";
import { logger } from "./utils/logger.js";
import { CONFIG } from "./config.js";
import type { MulticheckReport, AugmentedPipelineInput } from "./types/multicheck.js";
import type { PipelineCandidate } from "./types/candidates.js";
import type { GeoSignals } from "./types/signals.js";

const VERSION = "1.0.0";

async function main(): Promise<void> {
  const inputPath     = CONFIG.INPUT_PATH;
  const outputPath    = CONFIG.OUTPUT_PATH;
  const candidatesPath = process.argv[4];  // optional

  if (!inputPath || !outputPath) {
    process.stderr.write(
      "Usage: bun run src/index.ts <input.json> <output.json> [candidates.geojson]\n"
    );
    process.exit(1);
  }

  const totalStart = Date.now();
  logger.info("Multicheck start", { version: VERSION, inputPath, outputPath });

  // ── Load & validate input ─────────────────────────────────────────────────
  let rawInput: unknown;
  try {
    rawInput = JSON.parse(readFileSync(inputPath, "utf-8"));
  } catch (err) {
    logger.error("Failed to read input JSON", { err: String(err) });
    process.exit(1);
  }

  let pipelineInput;
  try {
    pipelineInput = PipelineInputSchema.parse(rawInput);
  } catch (err) {
    logger.error("Input JSON validation failed", { err: String(err) });
    process.exit(1);
  }

  const originalSignals = pipelineInput.geo_signals as GeoSignals;
  const imagePath       = pipelineInput.image_path as string | undefined ?? "";

  // ── Load candidates (optional, untuk CP3) ────────────────────────────────
  let candidates: PipelineCandidate[] = [];
  if (candidatesPath && existsSync(candidatesPath)) {
    try {
      const geojson = JSON.parse(readFileSync(candidatesPath, "utf-8")) as {
        features: Array<{ geometry: { coordinates: number[] }; properties: Record<string, unknown> }>;
      };
      candidates = geojson.features.map(f => ({
        lat:              f.geometry.coordinates[1],
        lon:              f.geometry.coordinates[0],
        name:             String(f.properties["name"] ?? "Unknown"),
        confidence_score: Number(f.properties["confidence_score"] ?? 0),
        confidence_label: String(f.properties["confidence_label"] ?? ""),
        radius_m:         Number(f.properties["radius_m"] ?? 5000),
        matched_signals:  (f.properties["matched_signals"] as string[]) ?? [],
        ai_reasoning:     String(f.properties["ai_reasoning"] ?? ""),
      }));
      logger.info("Loaded candidates", { count: candidates.length });
    } catch (err) {
      logger.warn("Failed to load candidates GeoJSON", { err: String(err) });
    }
  }

  // ── Run CP1: Signal Consensus ─────────────────────────────────────────────
  const cp1 = await runCP1(imagePath, originalSignals);
  const consensusSignals = { ...originalSignals, ...cp1.consensusSignals } as GeoSignals;

  // ── Run CP2: Geographic Coherence ─────────────────────────────────────────
  const cp2 = await runCP2(consensusSignals);

  // Apply CP2 hard-flagged signals ke consensus (set ke null)
  const verifiedSignals = { ...consensusSignals };
  for (const [field, weight] of Object.entries(cp2.adjustedWeights)) {
    if (weight === 0.0) {
      // HARD issue: hapus sinyal ini
      (verifiedSignals as Record<string, unknown>)[field] = null;
    }
  }

  // ── Run CP3: Coordinate Reverse-Verify (hanya jika ada candidates) ────────
  const cp3 = candidates.length > 0
    ? await runCP3(candidates, verifiedSignals)
    : null;

  // Build candidate score multipliers untuk Python
  const candidateMultipliers: Record<string, number> = {};
  if (cp3) {
    for (const v of cp3.verifications) {
      candidateMultipliers[v.candidateName] = v.scoreMult;
    }
  }

  // ── Run CP4: Confidence Gate ──────────────────────────────────────────────
  const cp4 = runCP4(cp1, cp2, cp3);

  // ── Assemble report ───────────────────────────────────────────────────────
  const report: MulticheckReport = {
    multicheckVersion:    VERSION,
    timestampMs:          Date.now(),
    cp1,
    cp2,
    cp3,
    cp4,
    verifiedGeoSignals:   verifiedSignals,
    candidateMultipliers,
    totalDurationMs:      Date.now() - totalStart,
  };

  // Augment original input dengan multicheck results
  const augmented: AugmentedPipelineInput = {
    ...(rawInput as Record<string, unknown>),
    geo_signals: verifiedSignals,
    multicheck:  report,
  } as AugmentedPipelineInput;

  // ── Write output ──────────────────────────────────────────────────────────
  try {
    writeFileSync(outputPath, JSON.stringify(augmented, null, 2), "utf-8");
    logger.info("Multicheck complete", {
      recommendation:   cp4.recommendation,
      hallucinationRisk: cp4.hallucinationRisk,
      hallucinationScore: cp4.hallucinationScore,
      totalDurationMs:  report.totalDurationMs,
    });
  } catch (err) {
    logger.error("Failed to write output JSON", { err: String(err) });
    process.exit(1);
  }

  // Exit code: 0 = PROCEED/CAUTION, 2 = REJECT (Python bisa check ini)
  if (cp4.recommendation === "REJECT") {
    process.exit(2);
  }
}

main().catch(err => {
  logger.error("Unhandled error in multicheck", { err: String(err) });
  process.exit(1);
});
