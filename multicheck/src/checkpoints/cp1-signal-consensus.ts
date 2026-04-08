// CP1: Signal Consensus
// Jalankan vision extraction 3x, vote per field, hasilkan consensus signals

import { runVisionExtraction } from "../providers/openaiClient.js";
import { VOTABLE_FIELDS, voteOnField, buildConsensusSignals } from "../utils/consensus.js";
import { logger } from "../utils/logger.js";
import { CONFIG } from "../config.js";
import type { CP1Result, ExtractionRun } from "../types/multicheck.js";
import type { GeoSignals } from "../types/signals.js";

export async function runCP1(
  imagePath:      string,
  originalSignals: GeoSignals,   // hasil extraction awal dari Python
): Promise<CP1Result> {
  const startMs = Date.now();
  logger.info("CP1 start", { imagePath, runs: CONFIG.CP1_RUN_COUNT });

  if (!imagePath) {
    // Tidak ada image path → skip re-runs, pakai original signals
    logger.warn("CP1 skip: no image_path provided, using original signals");
    return {
      passed: true,
      runs:   [],
      votes:  [],
      consensusSignals: originalSignals,
      rejectedFields:   [],
      durationMs: Date.now() - startMs,
    };
  }

  // Jalankan N extraction runs secara parallel
  const runPromises = Array.from({ length: CONFIG.CP1_RUN_COUNT }, async (_, i) => {
    const runStart = Date.now();
    try {
      const signals = await runVisionExtraction(imagePath);
      const run: ExtractionRun = {
        runIndex:   i,
        signals,
        durationMs: Date.now() - runStart,
      };
      logger.info(`CP1 run ${i} done`, { durationMs: run.durationMs });
      return run;
    } catch (err) {
      logger.error(`CP1 run ${i} failed`, { err: String(err) });
      return null;
    }
  });

  const results     = await Promise.all(runPromises);
  const successRuns = results.filter((r): r is ExtractionRun => r !== null);

  if (successRuns.length === 0) {
    logger.warn("CP1: all runs failed, fallback to original");
    return {
      passed: false,
      runs:   [],
      votes:  [],
      consensusSignals: originalSignals,
      rejectedFields:   VOTABLE_FIELDS as string[],
      durationMs: Date.now() - startMs,
    };
  }

  // Vote tiap field dari semua successful runs (+ original sebagai run-0)
  const allRuns = [
    { runIndex: -1, signals: originalSignals, durationMs: 0 } as ExtractionRun,
    ...successRuns,
  ];

  const votes = VOTABLE_FIELDS.map(field => {
    const values = allRuns.map(r => r.signals[field] ?? null);
    return voteOnField(field, values);
  });

  const rejectedFields  = votes.filter(v => !v.passed).map(v => v.field);
  const consensusSignals = buildConsensusSignals(votes, originalSignals);

  // CP1 passed jika lebih dari setengah votable fields ada majority
  const passedVotes = votes.filter(v => v.passed).length;
  const passed      = passedVotes >= Math.ceil(VOTABLE_FIELDS.length * 0.5);

  logger.info("CP1 done", {
    passed,
    passedVotes,
    total: VOTABLE_FIELDS.length,
    rejectedFields,
  });

  return {
    passed,
    runs:             successRuns,
    votes,
    consensusSignals,
    rejectedFields,
    durationMs: Date.now() - startMs,
  };
}
