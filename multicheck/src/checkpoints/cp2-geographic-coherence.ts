// CP2: Geographic Coherence
// Cek apakah signals konsisten secara geografis satu sama lain

import { readFileSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";
import { forwardGeocode } from "../providers/mapboxClient.js";
import { callOpenAIJSON } from "../providers/openaiClient.js";
import { CoherenceAssessmentSchema } from "../schemas/checkResultSchema.js";
import { buildCoherencePrompt } from "../utils/prompts.js";
import { bboxContains } from "../utils/geo.js";
import { logger } from "../utils/logger.js";
import { CONFIG } from "../config.js";
import type { CP2Result, CoherenceIssue } from "../types/multicheck.js";
import type { GeoSignals } from "../types/signals.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

// Baca plate_regions.json dari data/ folder Python
function loadPlateRegions(): Record<string, { bbox: number[]; region: string }> {
  const dataPath = join(__dirname, "../../../../data/plate_regions.json");
  try {
    return JSON.parse(readFileSync(dataPath, "utf-8")) as Record<string, { bbox: number[]; region: string }>;
  } catch {
    logger.warn("CP2: cannot load plate_regions.json, skipping bbox check");
    return {};
  }
}

export async function runCP2(signals: Partial<GeoSignals>): Promise<CP2Result> {
  const startMs     = Date.now();
  const plateRegions = loadPlateRegions();
  const issues:  CoherenceIssue[] = [];
  const adjustedWeights: Record<string, number> = {};

  logger.info("CP2 start", { plate: signals.plate_prefix, street: signals.street_name });

  // ── Check 1: Plate prefix → bbox containment ──────────────────────────────
  if (signals.plate_prefix && Object.keys(plateRegions).length > 0) {
    const plateData = plateRegions[signals.plate_prefix.toUpperCase()];
    if (plateData) {
      const [minLat, minLon, maxLat, maxLon] = plateData.bbox;
      const bboxStr = `${minLat},${minLon},${maxLat},${maxLon}`;

      // Jika area_name atau province ada, coba geocode untuk cek apakah masuk bbox
      const locationHint = signals.area_name ?? signals.city_district ?? signals.province;
      if (locationHint) {
        const geoResults = await forwardGeocode(locationHint, undefined, 1).catch(() => []);
        if (geoResults.length > 0) {
          const { lat, lon } = geoResults[0];
          const inside = bboxContains(bboxStr, lat, lon, CONFIG.CP2_BBOX_TOLERANCE_DEG);
          if (!inside) {
            issues.push({
              kind:     "PLATE_BBOX_MISMATCH",
              signal:   "plate_prefix",
              detail:   `Plate "${signals.plate_prefix}" maps to ${plateData.region}, but "${locationHint}" geocodes to (${lat.toFixed(3)},${lon.toFixed(3)}) which is outside that region`,
              severity: "HARD",
            });
            adjustedWeights["plate_prefix"]  = 0.0;
            adjustedWeights["street_name"]   = 0.2;   // HARD: jangan percaya street name juga
          }
        }
      }
    }
  }

  // ── Check 2: Street name → Mapbox validation dalam plate region ───────────
  if (signals.street_name && !("plate_prefix" in adjustedWeights && adjustedWeights["plate_prefix"] === 0)) {
    const plateData = signals.plate_prefix
      ? plateRegions[signals.plate_prefix.toUpperCase()]
      : null;
    const bboxStr = plateData
      ? `${plateData.bbox[0]},${plateData.bbox[1]},${plateData.bbox[2]},${plateData.bbox[3]}`
      : undefined;

    const streetResults = await forwardGeocode(
      signals.street_name,
      bboxStr,
      CONFIG.CP2_MAPBOX_STREET_LIMIT,
    ).catch(() => []);

    if (streetResults.length === 0) {
      // Street tidak ditemukan = kemungkinan besar halusinasi model vision
      // Ini adalah sinyal paling kuat untuk nullify street_name
      issues.push({
        kind:     "STREET_NOT_FOUND_IN_REGION",
        signal:   "street_name",
        detail:   `"${signals.street_name}" tidak ditemukan di Nominatim/Mapbox — kemungkinan OCR error atau halusinasi model`,
        severity: "HARD",
      });
      adjustedWeights["street_name"] = 0.0;  // hapus dari pipeline, jangan dipakai
    }
  }

  // ── Check 3: Claude cross-signal coherence assessment ─────────────────────
  let claudeAssessment = null;
  try {
    const { system, user } = buildCoherencePrompt(signals);
    claudeAssessment = await callOpenAIJSON(
      { systemPrompt: system, userPrompt: user, maxTokens: 512 },
      CoherenceAssessmentSchema,
    );

    // Tambah issues dari Claude
    for (const issue of claudeAssessment.issues) {
      // Jangan duplikasi issue yang sudah ada
      const exists = issues.some(i => i.kind === issue.kind && i.signal === issue.signal);
      if (!exists) {
        issues.push(issue);
        if (issue.severity === "HARD") {
          adjustedWeights[issue.signal] = 0.0;
        } else {
          adjustedWeights[issue.signal] = Math.min(
            adjustedWeights[issue.signal] ?? 1.0,
            0.4,
          );
        }
      }
    }

  } catch (err) {
    logger.warn("CP2: Claude coherence check failed", { err: String(err) });
  }

  const coherentSignals = claudeAssessment?.coherent_signals ?? [];
  const flaggedSignals  = [
    ...issues.map(i => i.signal),
    ...(claudeAssessment?.incoherent_signals ?? []),
  ].filter((v, i, a) => a.indexOf(v) === i);  // deduplicate

  // CP2 passed jika tidak ada HARD issues dan ≤ 1 SOFT issue
  const hardCount = issues.filter(i => i.severity === "HARD").length;
  const softCount = issues.filter(i => i.severity === "SOFT").length;
  const passed    = hardCount === 0 && softCount <= 1;

  logger.info("CP2 done", { passed, issues: issues.length, hard: hardCount, soft: softCount });

  return {
    passed,
    coherentSignals,
    flaggedSignals,
    issues,
    adjustedWeights,
    durationMs: Date.now() - startMs,
  };
}
