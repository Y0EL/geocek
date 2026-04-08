// Structured JSON logger ke stderr (agar tidak campur dengan output JSON ke stdout)

type LogLevel = "info" | "warn" | "error" | "debug";

function log(level: LogLevel, message: string, data?: unknown): void {
  const entry: Record<string, unknown> = {
    ts:    new Date().toISOString(),
    level,
    msg:   message,
  };
  if (data !== undefined) entry["data"] = data;
  process.stderr.write(JSON.stringify(entry) + "\n");
}

export const logger = {
  info:  (msg: string, data?: unknown) => log("info",  msg, data),
  warn:  (msg: string, data?: unknown) => log("warn",  msg, data),
  error: (msg: string, data?: unknown) => log("error", msg, data),
  debug: (msg: string, data?: unknown) => log("debug", msg, data),
};
