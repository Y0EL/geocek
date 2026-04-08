// CP3: Coordinate Reverse-Verification
// Untuk tiap top candidate, cek apakah koordinat konsisten dengan visual signals

import { tilequeryRoads, tilequeryPOIs } from "../providers/mapboxClient.js";
import { callOpenAIJSON } from "../providers/openaiClient.js";
import { ReverifyVerdictSchema } from "../schemas/checkResultSchema.js";
import { buildReverifyPrompt } from "../utils/prompts.js";
import { fuzzyMatch } from "../utils/geo.js";
import { logger } from "../utils/logger.js";
import type { CP3Result, ReverseVerification } from "../types/multicheck.js";
import type { PipelineCandidate } from "../types/candidates.js";
import type { GeoSignals } from "../types/signals.js";

// Score multiplier per verdict
const VERDICT_MULT: Record<string, number> = {
  CONSISTENT:   1.0,
  UNCERTAIN:    0.5,
  INCONSISTENT: 0.3,
};

export async function runCP3(
  candidates: PipelineCandidate[],
  signals:    Partial<GeoSignals>,
): Promise<CP3Result> {
  const startMs = Date.now();
  logger.info("CP3 start", { candidateCount: candidates.length });

  if (candidates.length === 0) {
    return {
      passed:        false,
      verifications: [],
      durationMs:    Date.now() - startMs,
    };
  }

  // Process top 3 candidates (lebih dari itu overkill)
  const topCandidates = candidates.slice(0, 3);

  const verifications = await Promise.all(
    topCandidates.map(async (candidate): Promise<ReverseVerification> => {
      const { lat, lon, name } = candidate;

      // Fetch road & POI data dari Mapbox
      const [roads, pois] = await Promise.all([
        tilequeryRoads(lat, lon).catch(() => []),
        tilequeryPOIs(lat, lon).catch(() => []),
      ]);

      logger.debug("CP3 tilequery result", {
        candidate: name,
        roads: roads.map(r => r.name),
        pois:  pois.map(p => p.name),
      });

      // Quick pre-check: fuzzy match street name dengan roads dari Mapbox
      const roadNames = roads.map(r => r.name);
      const poiNames  = pois.map(p => p.name);

      // Kalau street_name match dengan mapbox road → bonus confidence
      const streetInRoads = signals.street_name
        ? roadNames.some(r => fuzzyMatch(r, signals.street_name!))
        : false;

      // Kalau poi_list ada item yang match → bonus
      const poisMatch = (signals.poi_list ?? []).some(poi =>
        poiNames.some(mp => fuzzyMatch(mp, poi))
      );

      // Kirim ke Claude untuk final verdict
      let claudeVerdict: "CONSISTENT" | "INCONSISTENT" | "UNCERTAIN" = "UNCERTAIN";
      let claudeReasoning = "Claude check not performed";

      try {
        const { system, user } = buildReverifyPrompt(
          name, lat, lon, roads, pois, signals,
        );
        const verdict = await callOpenAIJSON(
          { systemPrompt: system, userPrompt: user, maxTokens: 400 },
          ReverifyVerdictSchema,
        );
        claudeVerdict   = verdict.verdict;
        claudeReasoning = verdict.reasoning;

        // Jika quick pre-check sangat positif tapi Claude uncertain → upgrade ke CONSISTENT
        if (
          claudeVerdict === "UNCERTAIN" &&
          (streetInRoads || poisMatch) &&
          verdict.signals_contradicted.length === 0
        ) {
          claudeVerdict   = "CONSISTENT";
          claudeReasoning += " [upgraded: strong quick-match evidence]";
        }
      } catch (err) {
        logger.warn("CP3: Claude reverify failed for candidate", { candidate: name, err: String(err) });
        // Fallback: pakai quick pre-check
        if (streetInRoads && poisMatch) {
          claudeVerdict   = "CONSISTENT";
          claudeReasoning = "Quick fuzzy match: street and POI both found near coordinates";
        } else if (!streetInRoads && !poisMatch) {
          claudeVerdict   = "INCONSISTENT";
          claudeReasoning = "Quick fuzzy match: neither street nor POI found near coordinates";
        }
      }

      const scoreMult = VERDICT_MULT[claudeVerdict] ?? 0.5;
      const passed    = claudeVerdict !== "INCONSISTENT";

      logger.info("CP3 candidate done", { name, verdict: claudeVerdict, scoreMult });

      return {
        candidateName:    name,
        lat,
        lon,
        mapboxRoadsFound: roadNames,
        mapboxPoisFound:  poiNames,
        claudeVerdict,
        claudeReasoning,
        scoreMult,
        passed,
      };
    })
  );

  // CP3 passed jika mayoritas top candidates CONSISTENT atau UNCERTAIN
  const passedCount = verifications.filter(v => v.passed).length;
  const passed      = passedCount >= Math.ceil(verifications.length / 2);

  logger.info("CP3 done", { passed, passedCount, total: verifications.length });

  return {
    passed,
    verifications,
    durationMs: Date.now() - startMs,
  };
}
