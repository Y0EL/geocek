import { CONFIG } from "../config.js";

// Exponential backoff dengan jitter
export async function withRetry<T>(
  fn:          () => Promise<T>,
  maxAttempts: number = CONFIG.RETRY_MAX_ATTEMPTS,
  baseDelayMs: number = CONFIG.RETRY_BASE_DELAY_MS,
): Promise<T> {
  let lastError: unknown;

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastError = err;

      if (attempt === maxAttempts) break;

      // Exponential backoff: baseDelay * 2^(attempt-1) + jitter
      const exponential = baseDelayMs * Math.pow(2, attempt - 1);
      const jitter      = Math.random() * baseDelayMs;
      const delay       = Math.min(exponential + jitter, CONFIG.RETRY_MAX_DELAY_MS);

      await sleep(delay);
    }
  }

  throw lastError;
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
