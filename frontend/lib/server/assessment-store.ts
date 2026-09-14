import "server-only";
import type { BankQuestion } from "./assessment-bank";
import { advanceQuestion, answerQuestion, AssessmentError, assessmentView, goBack, parseSetup, startAssessment, startBookAssessment, withDeferredResults, type AssessmentState } from "./assessment-engine";
import { retentionDays } from "./config";
import { database } from "./database";
import { json } from "./http";
import { sessionFor } from "./session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
async function body(request: Request): Promise<Record<string, unknown>> {
  const origin = request.headers.get("origin");
  if (origin && origin !== new URL(request.url).origin) throw new AssessmentError("invalid_origin", 403);
  if (!request.headers.get("content-type")?.startsWith("application/json")) throw new AssessmentError("invalid_content_type", 415);
  const reader = request.body?.getReader();
  if (!reader) throw new AssessmentError("invalid_json");
  let size = 0;
  const chunks: Uint8Array[] = [];
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    size += value.length;
    if (size > 8192) { await reader.cancel(); throw new AssessmentError("request_too_large", 413); }
    chunks.push(value);
  }
  try {
    const parsed: unknown = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error();
    return parsed as Record<string, unknown>;
  } catch { throw new AssessmentError("invalid_json"); }
}

export async function assessmentRequest(request: Request, id?: string) {
  try {
    const session = sessionFor(request);
    const sql = database();
    if (id && !uuid.test(id)) throw new AssessmentError("invalid_session_id");
    if (request.method === "GET") {
      const rows = id ? await sql<{ state: AssessmentState }[]>`
        SELECT state FROM java_assessment_sessions WHERE id = ${id} AND owner_hash = ${session.ownerHash} AND expires_at > now()`
        : await sql<{ state: AssessmentState }[]>`
        SELECT state FROM java_assessment_sessions WHERE owner_hash = ${session.ownerHash} AND expires_at > now() ORDER BY created_at DESC, id DESC LIMIT 1`;
      if (id && !rows.length) throw new AssessmentError("session_not_found", 404);
      return json({ assessment: rows[0] ? assessmentView(rows[0].state) : null }, 200, session);
    }
    const input = await body(request);
    if (!id) {
      const setup = parseSetup(input);
      if (typeof input.requestId !== "string" || !uuid.test(input.requestId)) throw new AssessmentError("invalid_request_id");
      const newId = input.requestId;
      const state = await sql.begin(async (tx) => {
        await tx`SELECT pg_advisory_xact_lock(hashtextextended(${session.ownerHash}, 0))`;
        const existing = await tx<{ state: AssessmentState }[]>`SELECT state FROM java_assessment_sessions WHERE id = ${newId} AND owner_hash = ${session.ownerHash} AND expires_at > now()`;
        if (existing[0]) {
          const s = existing[0].state;
          if ((s.mode ?? "roadmap") !== setup.mode || s.level !== setup.level || s.company !== setup.company || JSON.stringify(s.topicIds) !== JSON.stringify(setup.topicIds)) throw new AssessmentError("request_id_reused", 409);
          return s;
        }
        const recent = await tx<{ count: number }[]>`SELECT count(*)::int AS count FROM java_assessment_sessions WHERE owner_hash = ${session.ownerHash} AND created_at > now() - interval '10 minutes'`;
        if (recent[0].count >= 10) throw new AssessmentError("rate_limited", 429);
        const rows = setup.mode === "book"
          ? await tx<{ question: BankQuestion; status: BankQuestion["status"] }[]>`
            SELECT question, status FROM java_question_bank WHERE status = 'published'
              AND question->>'collection' = 'book' ORDER BY random() LIMIT 15`
          : await tx<{ question: BankQuestion; status: BankQuestion["status"] }[]>`
            SELECT question, status FROM (
              SELECT DISTINCT ON (id) question, status FROM java_question_bank WHERE status <> 'draft' ORDER BY id, version DESC
            ) latest WHERE status = 'published' AND question->>'collection' IS DISTINCT FROM 'book'`;
        const bank = rows.map((r) => ({ ...r.question, status: r.status }));
        const next = withDeferredResults(setup.mode === "book" ? startBookAssessment(newId, bank) : startAssessment(newId, setup, bank));
        await tx`INSERT INTO java_assessment_sessions (id, owner_hash, state, expires_at)
          VALUES (${newId}, ${session.ownerHash}, ${tx.json(next)}, now() + (${retentionDays()} * interval '1 day'))`;
        return next;
      });
      return json({ assessment: assessmentView(state) }, 201, session);
    }
    const state = await sql.begin(async (tx) => {
      const rows = await tx<{ state: AssessmentState }[]>`
        SELECT state FROM java_assessment_sessions WHERE id = ${id} AND owner_hash = ${session.ownerHash} AND expires_at > now() FOR UPDATE`;
      if (!rows[0]) throw new AssessmentError("session_not_found", 404);
      let next = rows[0].state;
      if (input.action === "answer") {
        next = next.flowVersion === 2
          ? advanceQuestion(next, input.questionId, input.selected)
          : answerQuestion(next, input.questionId, input.selected);
      } else if (input.action === "back") {
        next = goBack(next);
      } else if (input.action === "finish") {
        if (!next.answers.length) throw new AssessmentError("answer_required");
        const finalTurn = next.flowVersion === 2 && next.currentId && next.turnIds
          && next.cursor === next.turnIds.length - 1
          && next.answers.some((answer) => answer.questionId === next.currentId);
        next = { ...next, finishedEarly: next.finishedEarly || (Boolean(next.currentId) && !finalTurn), currentId: null };
      } else if (input.action === "feedback") {
        if (next.flowVersion === 2 && next.currentId) throw new AssessmentError("assessment_not_complete", 409);
        const answer = next.answers.find((a) => a.questionId === input.questionId);
        const question = next.questions.find((q) => q.id === input.questionId);
        if (!answer || !question) throw new AssessmentError("answer_required");
        if (input.rating !== undefined && input.rating !== null && (!Number.isInteger(input.rating) || (input.rating as number) < 1 || (input.rating as number) > 5)) throw new AssessmentError("invalid_rating");
        if (input.flag !== undefined && input.flag !== null && !["incorrect", "unclear", "too_difficult", "source"].includes(input.flag as string)) throw new AssessmentError("invalid_flag");
        if (input.rating === undefined && input.flag === undefined) throw new AssessmentError("feedback_required");
        const rating = input.rating === undefined ? answer.rating : input.rating as number | null;
        const flag = input.flag === undefined ? answer.flag : input.flag as string | null;
        await tx`INSERT INTO java_question_feedback (owner_hash, question_id, question_version, rating, flag, expires_at)
          VALUES (${session.ownerHash}, ${question.id}, ${question.version}, ${rating}, ${flag}, now() + (${retentionDays()} * interval '1 day'))
          ON CONFLICT (owner_hash, question_id, question_version) DO UPDATE SET
          rating = EXCLUDED.rating, flag = EXCLUDED.flag, review_status = 'pending', updated_at = now(), expires_at = EXCLUDED.expires_at`;
        next = { ...next, answers: next.answers.map((a) => a.questionId === question.id ? { ...a, rating, flag } : a) };
      } else { throw new AssessmentError("invalid_action"); }
      await tx`UPDATE java_assessment_sessions SET state = ${tx.json(next)} WHERE id = ${id} AND owner_hash = ${session.ownerHash}`;
      return next;
    });
    return json({ assessment: assessmentView(state) }, 200, session);
  } catch (error) {
    if (error instanceof AssessmentError) return json({ code: error.message }, error.status);
    console.error("Assessment request failed", error instanceof Error ? error.name : "unknown_error");
    return json({ code: "assessment_unavailable" }, 503);
  }
}
