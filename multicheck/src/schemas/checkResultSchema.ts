import { z } from "zod";

// CP3: Verdict dari Claude untuk reverse-verification satu kandidat
export const ReverifyVerdictSchema = z.object({
  verdict:              z.enum(["CONSISTENT", "INCONSISTENT", "UNCERTAIN"]),
  reasoning:            z.string().max(600),
  signals_matched:      z.array(z.string()),
  signals_contradicted: z.array(z.string()),
});

// CP2: Assessment dari Claude untuk cross-signal geographic coherence
export const CoherenceAssessmentSchema = z.object({
  coherent_signals:   z.array(z.string()),
  incoherent_signals: z.array(z.string()),
  issues: z.array(z.object({
    kind: z.enum([
      "PLATE_BBOX_MISMATCH",
      "STREET_NOT_FOUND_IN_REGION",
      "SIGNALS_POINT_TO_DIFFERENT_AREAS",
      "PROVINCE_CITY_MISMATCH",
    ]),
    signal:   z.string(),
    detail:   z.string().max(300),
    severity: z.enum(["HARD", "SOFT"]),
  })),
  overall_coherent: z.boolean(),
});

export type ReverifyVerdict     = z.infer<typeof ReverifyVerdictSchema>;
export type CoherenceAssessment = z.infer<typeof CoherenceAssessmentSchema>;
