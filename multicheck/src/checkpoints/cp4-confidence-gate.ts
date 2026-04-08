// CP4: Confidence Gate
// Agregasi hasil CP1-CP3 → hallucination score + recommendation

import { logger } from "../utils/logger.js";
import { CONFIG } from "../config.js";
import type { CP1Result, CP2Result, CP3Result, CP4Result, HallucinationRisk } from "../types/multicheck.js";

export function runCP4(
  cp1: CP1Result,
  cp2: CP2Result,
  cp3: CP3Result | null,
): CP4Result {
  logger.info("CP4 start", {
    cp1Passed: cp1.passed,
    cp2Passed: cp2.passed,
    cp3Passed: cp3?.passed ?? null,
  });

  // Hitung checkpoints yang passed
  let checkpointsPassed = 0;
  if (cp1.passed) checkpointsPassed++;
  if (cp2.passed) checkpointsPassed++;
  if (cp3 !== null && cp3.passed) checkpointsPassed++;

  // Kumpulkan signals yang konsisten vs kontradiktif
  const consistentSignals:    string[] = [...cp2.coherentSignals];
  const contradictorySignals: string[] = [...cp2.flaggedSignals];

  // Dari CP1: rejected fields = contradictory
  for (const f of cp1.rejectedFields) {
    if (!contradictorySignals.includes(f)) contradictorySignals.push(f);
  }

  // Dari CP3: tambah candidate-level info ke contradictory jika INCONSISTENT
  if (cp3) {
    const inconsistentCands = cp3.verifications.filter(v => v.claudeVerdict === "INCONSISTENT");
    if (inconsistentCands.length > 0) {
      const label = `coordinates(${inconsistentCands.map(c => c.candidateName).join(", ")})`;
      if (!contradictorySignals.includes(label)) contradictorySignals.push(label);
    }
  }

  // Hitung hallucination score (0.0 = clean, 1.0 = fully hallucinated)
  let score = 0.0;

  // CP1 contribution: proportion rejected fields
  const cp1Contrib = cp1.votes.length > 0
    ? cp1.rejectedFields.length / cp1.votes.length
    : 0;
  score += cp1Contrib * 0.35;   // bobot 35%

  // CP2 contribution: HARD issues = 0.5 each, SOFT = 0.2 each, max 1.0
  const hardCount = cp2.issues.filter(i => i.severity === "HARD").length;
  const softCount = cp2.issues.filter(i => i.severity === "SOFT").length;
  const cp2Contrib = Math.min(1.0, hardCount * 0.5 + softCount * 0.2);
  score += cp2Contrib * 0.35;   // bobot 35%

  // CP3 contribution: proportion of INCONSISTENT candidates
  if (cp3 && cp3.verifications.length > 0) {
    const inconsistentCount = cp3.verifications.filter(v => v.claudeVerdict === "INCONSISTENT").length;
    const cp3Contrib = inconsistentCount / cp3.verifications.length;
    score += cp3Contrib * 0.30;  // bobot 30%
  }

  // Classify risk
  let hallucinationRisk: HallucinationRisk;
  if (score < 0.3) {
    hallucinationRisk = "LOW";
  } else if (score < CONFIG.CP4_HIGH_RISK_THRESHOLD) {
    hallucinationRisk = "MEDIUM";
  } else {
    hallucinationRisk = "HIGH";
  }

  // Recommendation
  // CP3 selalu null di fase pre-pipeline (sebelum candidates ada), jadi max checkpoint bisa hanya 2.
  // Kalau hallucinationScore = 0 dan risk LOW → langsung PROCEED tanpa perlu hitung checkpoint.
  let recommendation: CP4Result["recommendation"];
  if (hallucinationRisk === "LOW" && score === 0) {
    recommendation = "PROCEED";
  } else if (checkpointsPassed >= CONFIG.CP4_MIN_CHECKPOINTS_PASSED && hallucinationRisk !== "HIGH") {
    recommendation = "PROCEED";
  } else if (hallucinationRisk === "HIGH") {
    recommendation = "REJECT";
  } else {
    recommendation = "PROCEED_WITH_CAUTION";
  }

  const passed = recommendation !== "REJECT";

  logger.info("CP4 done", {
    passed,
    checkpointsPassed,
    hallucinationScore: score.toFixed(3),
    hallucinationRisk,
    recommendation,
  });

  return {
    passed,
    checkpointsPassed,
    hallucinationRisk,
    hallucinationScore: Math.round(score * 1000) / 1000,
    consistentSignals,
    contradictorySignals,
    recommendation,
  };
}
