import type { InterviewDetails, PracticeFeedback, PracticeReport } from "../../../../../lib/interview-api";
import { database } from "../../../../../lib/server/database";
import { json } from "../../../../../lib/server/http";
import { createPracticeReport } from "../../../../../lib/server/interview-ai";
import { opaqueSafetyIdentifier, sessionFor } from "../../../../../lib/server/session";

export const runtime = "nodejs";
export const maxDuration = 120;

type SessionRow = {
  id: string;
  mode: string;
  report: PracticeReport | null;
  input: InterviewDetails;
};

type TurnRow = { prompt: string; answer: string; feedback: PracticeFeedback };

export async function POST(request: Request, context: { params: Promise<{ sessionId: string }> }) {
  const session = sessionFor(request);
  const { sessionId } = await context.params;
  if (!/^[0-9a-f-]{36}$/i.test(sessionId)) return json({ code: "not_found" }, 404, session);
  const sql = database();
  const sessions = await sql<SessionRow[]>`
    SELECT s.id, s.mode, s.report, p.input
    FROM interview_practice_sessions s
    JOIN interview_preparations p ON p.id = s.preparation_id
    WHERE s.id = ${sessionId} AND s.owner_hash = ${session.ownerHash} AND s.expires_at > now()
  `;
  const row = sessions[0];
  if (!row) return json({ code: "practice_session_not_found" }, 404, session);
  if (row.report) return json({ report: row.report }, 200, session);
  const turns = await sql<TurnRow[]>`
    SELECT prompt, answer, feedback FROM interview_practice_turns
    WHERE session_id = ${sessionId} ORDER BY sequence
  `;
  if (!turns.length) return json({ code: "practice_has_no_answers" }, 409, session);

  try {
    const report = await createPracticeReport({
      details: row.input,
      mode: row.mode,
      turns,
      safetyIdentifier: opaqueSafetyIdentifier(session),
    });
    await sql`
      UPDATE interview_practice_sessions
      SET status = 'completed', report = ${sql.json(report)}, updated_at = now()
      WHERE id = ${sessionId} AND owner_hash = ${session.ownerHash} AND report IS NULL
    `;
    return json({ report }, 200, session);
  } catch (error) {
    console.error("Practice report generation failed", error instanceof Error ? error.message : "unknown_error");
    return json({ code: "report_unavailable" }, 502, session);
  }
}
