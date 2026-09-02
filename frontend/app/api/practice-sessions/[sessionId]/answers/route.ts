import type { InterviewAnalysis, InterviewDetails, PracticeFeedback, PreparationQuestion } from "../../../../../lib/interview-api";
import { database } from "../../../../../lib/server/database";
import { json } from "../../../../../lib/server/http";
import { evaluatePracticeAnswer } from "../../../../../lib/server/interview-ai";
import { opaqueSafetyIdentifier, sessionFor } from "../../../../../lib/server/session";

export const runtime = "nodejs";
export const maxDuration = 120;

type SessionRow = {
  id: string;
  mode: "Real Interview" | "Practice";
  question_ids: string[];
  current_index: number;
  awaiting_follow_up: boolean;
  pending_follow_up: string | null;
  status: "active" | "completed";
  analysis: InterviewAnalysis;
  input: InterviewDetails;
};

function findQuestion(row: SessionRow): PreparationQuestion | null {
  const id = row.question_ids[row.current_index];
  return row.analysis.questions.find((question) => question.id === id) ?? null;
}

export async function POST(request: Request, context: { params: Promise<{ sessionId: string }> }) {
  const session = sessionFor(request);
  const { sessionId } = await context.params;
  if (!/^[0-9a-f-]{36}$/i.test(sessionId)) return json({ code: "not_found" }, 404, session);
  let answer = "";
  try {
    const body = await request.json() as { answer?: unknown };
    answer = typeof body.answer === "string" ? body.answer.trim() : "";
  } catch {
    return json({ code: "invalid_json" }, 400, session);
  }
  if (answer.length < 30 || answer.length > 2_500) return json({ code: "invalid_answer" }, 400, session);

  const sql = database();
  const rows = await sql<SessionRow[]>`
    SELECT s.id, s.mode, s.question_ids, s.current_index, s.awaiting_follow_up,
           s.pending_follow_up, s.status, p.analysis, p.input
    FROM interview_practice_sessions s
    JOIN interview_preparations p ON p.id = s.preparation_id
    WHERE s.id = ${sessionId} AND s.owner_hash = ${session.ownerHash}
      AND s.status = 'active' AND s.expires_at > now()
  `;
  const row = rows[0];
  if (!row) return json({ code: "practice_session_not_found" }, 404, session);
  const question = findQuestion(row);
  if (!question) return json({ code: "practice_state_invalid" }, 409, session);
  const kind = row.awaiting_follow_up ? "follow_up" as const : "question" as const;
  const prompt = kind === "follow_up" ? row.pending_follow_up : question.question;
  if (!prompt) return json({ code: "practice_state_invalid" }, 409, session);

  let feedback: PracticeFeedback;
  try {
    feedback = await evaluatePracticeAnswer({
      details: row.input,
      question: prompt,
      answer,
      kind,
      language: row.input.language,
      safetyIdentifier: opaqueSafetyIdentifier(session),
    });
  } catch (error) {
    console.error("Practice answer evaluation failed", error instanceof Error ? error.message : "unknown_error");
    return json({ code: "feedback_unavailable" }, 502, session);
  }
  if (kind === "question" && !feedback.adaptiveFollowUp) feedback.adaptiveFollowUp = question.followUp;

  try {
    const result = await sql.begin(async (transaction) => {
      const current = await transaction<Pick<SessionRow, "current_index" | "awaiting_follow_up" | "status">[]>`
        SELECT current_index, awaiting_follow_up, status
        FROM interview_practice_sessions
        WHERE id = ${sessionId} AND owner_hash = ${session.ownerHash}
        FOR UPDATE
      `;
      const state = current[0];
      if (!state || state.status !== "active"
        || state.current_index !== row.current_index
        || state.awaiting_follow_up !== row.awaiting_follow_up) {
        throw new Error("practice_state_changed");
      }
      const sequence = row.current_index * 2 + (kind === "follow_up" ? 1 : 0);
      await transaction`
        INSERT INTO interview_practice_turns (
          session_id, sequence, question_id, kind, prompt, answer, feedback
        ) VALUES (
          ${sessionId}, ${sequence}, ${question.id}, ${kind}, ${prompt}, ${answer},
          ${transaction.json(feedback)}
        )
      `;
      if (kind === "question") {
        await transaction`
          UPDATE interview_practice_sessions
          SET awaiting_follow_up = true, pending_follow_up = ${feedback.adaptiveFollowUp}, updated_at = now()
          WHERE id = ${sessionId}
        `;
        return { followUp: feedback.adaptiveFollowUp, nextQuestion: false, sessionComplete: false };
      }
      const nextIndex = row.current_index + 1;
      const complete = nextIndex >= row.question_ids.length;
      await transaction`
        UPDATE interview_practice_sessions
        SET awaiting_follow_up = false, pending_follow_up = NULL, current_index = ${nextIndex}, updated_at = now()
        WHERE id = ${sessionId}
      `;
      return { followUp: null, nextQuestion: !complete, sessionComplete: complete };
    });
    return json({ feedback, ...result }, 200, session);
  } catch (error) {
    const code = error instanceof Error && error.message === "practice_state_changed"
      ? "practice_state_changed"
      : "answer_save_failed";
    return json({ code }, 409, session);
  }
}
