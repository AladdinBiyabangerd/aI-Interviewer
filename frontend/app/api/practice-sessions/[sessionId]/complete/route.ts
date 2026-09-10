import { publicInterviewGuard } from "../../../../../lib/server/interview-access";
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
  const blocked = publicInterviewGuard();
  if (blocked) return blocked;
  const session = sessionFor(request);
  const { sessionId } = await context.params;
  if (!/^[0-9a-f-]{36}$/i.test(sessionId)) return json({ code: "not_found" }, 404, session);
  const sql = database();

  try {
    const report = await sql.begin(async (transaction) => {
      const sessions = await transaction<SessionRow[]>`
        SELECT s.id, s.mode, s.report, p.input
        FROM interview_practice_sessions s
        JOIN interview_preparations p ON p.id = s.preparation_id
        WHERE s.id = ${sessionId} AND s.owner_hash = ${session.ownerHash} AND s.expires_at > now()
        FOR UPDATE OF s
      `;
      const row = sessions[0];
      if (!row) throw new Error("practice_session_not_found");
      // Held for the OpenAI call below so a concurrent finish for this
      // session blocks here and then reuses the report just written,
      // instead of both racing to generate (and pay for) their own.
      if (row.report) return row.report;

      const turns = await transaction<TurnRow[]>`
        SELECT prompt, answer, feedback FROM interview_practice_turns
        WHERE session_id = ${sessionId} ORDER BY sequence
      `;
      if (!turns.length) throw new Error("practice_has_no_answers");

      const generated = await createPracticeReport({
        details: row.input,
        mode: row.mode,
        turns,
        safetyIdentifier: opaqueSafetyIdentifier(session),
      });
      await transaction`
        UPDATE interview_practice_sessions
        SET status = 'completed', report = ${transaction.json(generated)}, updated_at = now()
        WHERE id = ${sessionId} AND owner_hash = ${session.ownerHash}
      `;
      return generated;
    });
    return json({ report }, 200, session);
  } catch (error) {
    const message = error instanceof Error ? error.message : "unknown_error";
    if (message === "practice_session_not_found") return json({ code: "practice_session_not_found" }, 404, session);
    if (message === "practice_has_no_answers") return json({ code: "practice_has_no_answers" }, 409, session);
    console.error("Practice report generation failed", message);
    return json({ code: "report_unavailable" }, 502, session);
  }
}
