import { EXPECTED_DATABASE_REVISION } from "../../../lib/server/config";
import { database } from "../../../lib/server/database";
import { json } from "../../../lib/server/http";
import { defaultTopics, levels } from "../../../lib/assessment";
import type { BankQuestion } from "../../../lib/server/assessment-bank";
import { startAssessment } from "../../../lib/server/assessment-engine";

export const runtime = "nodejs";
export const maxDuration = 10;
export const dynamic = "force-dynamic";

export async function GET() {
  const required = [
    "DATABASE_URL",
    "INTERVIEW_SESSION_SECRET",
    "CRON_SECRET",
  ];
  const missing = required.filter((name) => !process.env[name]?.trim());
  if (missing.length) return json({ status: "not_ready", code: "configuration_incomplete" }, 503);
  try {
    const rows = await database()<{ version_num: string }[]>`SELECT version_num FROM alembic_version`;
    if (rows[0]?.version_num !== EXPECTED_DATABASE_REVISION) {
      return json({ status: "not_ready", code: "database_revision_mismatch" }, 503);
    }
    const bank = await database()<{ question: BankQuestion }[]>`SELECT question FROM (
      SELECT DISTINCT ON (id) question, status FROM java_question_bank WHERE status <> 'draft' ORDER BY id, version DESC
    ) latest WHERE status = 'published' AND question->>'collection' IS DISTINCT FROM 'book'`;
    try {
      for (const level of levels) startAssessment("readiness", { level, topicIds: defaultTopics[level], company: null }, bank.map((r) => ({ ...r.question, status: "published" })));
    } catch { return json({ status: "not_ready", code: "question_bank_incomplete" }, 503); }
    return json({ status: "ready", databaseRevision: EXPECTED_DATABASE_REVISION });
  } catch (error) {
    console.error("Health dependency check failed", error instanceof Error ? error.name : "unknown_error");
    return json({ status: "not_ready", code: "database_unavailable" }, 503);
  }
}
