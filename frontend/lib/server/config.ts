import "server-only";

export const EXPECTED_DATABASE_REVISION = "20260910_0016";

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`Missing required server environment variable: ${name}`);
  return value;
}

function boundedInteger(name: string, fallback: number, minimum: number, maximum: number): number {
  const raw = process.env[name]?.trim();
  if (!raw) return fallback;
  const value = Number.parseInt(raw, 10);
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${name} must be an integer between ${minimum} and ${maximum}`);
  }
  return value;
}

export function databaseUrl(): string {
  return required("DATABASE_URL");
}

export function sessionSecret(): string {
  const value = required("INTERVIEW_SESSION_SECRET");
  if (Buffer.byteLength(value, "utf8") < 32) {
    throw new Error("INTERVIEW_SESSION_SECRET must contain at least 32 bytes");
  }
  return value;
}

export function openAIKey(): string {
  return required("OPENAI_API_KEY");
}

export function openAIModel(): string {
  return process.env.OPENAI_INTERVIEW_MODEL?.trim() || "gpt-5.5";
}

export function retentionDays(): number {
  return boundedInteger("INTERVIEW_RETENTION_DAYS", 7, 1, 30);
}

export function analysisLimit(): number {
  return boundedInteger("INTERVIEW_ANALYSIS_LIMIT_PER_10_MINUTES", 5, 1, 50);
}

export function cronSecret(): string {
  return required("CRON_SECRET");
}
