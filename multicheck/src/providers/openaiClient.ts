import OpenAI from "openai";
import { readFileSync } from "fs";
import { env, CONFIG } from "../config.js";
import { withRetry } from "../utils/retry.js";
import { GeoSignalsSchema } from "../schemas/signalSchema.js";
import type { ValidatedGeoSignals } from "../schemas/signalSchema.js";
import { VISION_SYSTEM_PROMPT, VISION_USER_PROMPT } from "../utils/prompts.js";

const client = new OpenAI({ apiKey: env.OPENAI_API_KEY });

// ─── Vision Extraction (CP1) ──────────────────────────────────────────────────

// Jalankan satu run vision extraction pada image_path
export async function runVisionExtraction(
  imagePath: string,
): Promise<ValidatedGeoSignals> {
  return withRetry(async () => {
    const imageBuffer = readFileSync(imagePath);
    const base64Image = imageBuffer.toString("base64");
    const mimeType    = imagePath.toLowerCase().endsWith(".png") ? "image/png" : "image/jpeg";

    const response = await client.chat.completions.create({
      model:       CONFIG.VISION_MODEL,
      temperature: 0.1,
      max_tokens:  2048,
      response_format: { type: "json_object" },
      messages: [
        { role: "system", content: VISION_SYSTEM_PROMPT },
        {
          role: "user",
          content: [
            {
              type: "image_url",
              image_url: { url: `data:${mimeType};base64,${base64Image}` },
            },
            { type: "text", text: VISION_USER_PROMPT },
          ],
        },
      ],
    });

    const raw = response.choices[0]?.message?.content ?? "{}";
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      throw new Error(`Vision model returned non-JSON: ${raw.slice(0, 200)}`);
    }

    const candidate = (parsed as Record<string, unknown>)["geo_signals"] ?? parsed;
    return GeoSignalsSchema.parse(candidate);
  }, CONFIG.RETRY_MAX_ATTEMPTS, CONFIG.RETRY_BASE_DELAY_MS);
}

// ─── JSON reasoning calls (CP2 + CP3) ────────────────────────────────────────

export interface OpenAITextRequest {
  systemPrompt: string;
  userPrompt:   string;
  maxTokens?:   number;
  temperature?: number;
}

// Panggil OpenAI dan parse JSON response dengan Zod schema
export async function callOpenAIJSON<T>(
  req:    OpenAITextRequest,
  schema: { parse: (v: unknown) => T },
): Promise<T> {
  return withRetry(async () => {
    const response = await client.chat.completions.create({
      model:           CONFIG.REASONING_MODEL,
      temperature:     req.temperature ?? 0,
      max_tokens:      req.maxTokens   ?? 1024,
      response_format: { type: "json_object" },
      messages: [
        {
          role:    "system",
          content: req.systemPrompt +
            "\n\nIMPORTANT: Respond ONLY with valid JSON. No markdown fences, no explanation.",
        },
        { role: "user", content: req.userPrompt },
      ],
    });

    const raw = response.choices[0]?.message?.content ?? "{}";
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      throw new Error(`OpenAI returned non-JSON: ${raw.slice(0, 200)}`);
    }

    return schema.parse(parsed);
  }, CONFIG.RETRY_MAX_ATTEMPTS, CONFIG.RETRY_BASE_DELAY_MS);
}
