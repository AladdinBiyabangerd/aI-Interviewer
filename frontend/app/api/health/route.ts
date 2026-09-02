import { EXPECTED_DATABASE_REVISION } from "../../../lib/server/config";
import { database } from "../../../lib/server/database";
import { json } from "../../../lib/server/http";

export const runtime = "nodejs";
export const maxDuration = 10;
export const dynamic = "force-dynamic";

export async function GET() {
  const required = [
    "DATABASE_URL",
    "BLOB_READ_WRITE_TOKEN",
    "OPENAI_API_KEY",
    "INTERVIEW_SESSION_SECRET",
    "OPENAI_WEBHOOK_SECRET",
    "CRON_SECRET",
  ];
  const missing = required.filter((name) => !process.env[name]?.trim());
  if (missing.length) return json({ status: "not_ready", code: "configuration_incomplete" }, 503);
  try {
    const rows = await database()<{ version_num: string }[]>`SELECT version_num FROM alembic_version`;
    if (rows[0]?.version_num !== EXPECTED_DATABASE_REVISION) {
      return json({ status: "not_ready", code: "database_revision_mismatch" }, 503);
    }
    return json({ status: "ready", databaseRevision: EXPECTED_DATABASE_REVISION });
  } catch (error) {
    console.error("Health dependency check failed", error instanceof Error ? error.name : "unknown_error");
    return json({ status: "not_ready", code: "database_unavailable" }, 503);
  }
}
