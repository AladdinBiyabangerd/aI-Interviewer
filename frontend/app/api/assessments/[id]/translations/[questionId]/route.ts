import { createHash } from "node:crypto";

import type { AssessmentState } from "../../../../../../lib/server/assessment-engine";
import { translateAssessmentQuestion } from "../../../../../../lib/server/assessment-translation";
import { database } from "../../../../../../lib/server/database";
import { json } from "../../../../../../lib/server/http";
import { sessionFor } from "../../../../../../lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const questionKey = /^[a-z0-9-]{1,100}$/;
type Context = { params: Promise<{ id: string; questionId: string }> };

export async function GET(request: Request, context: Context) {
  const session = sessionFor(request);
  try {
    const { id, questionId } = await context.params;
    if (!uuid.test(id) || !questionKey.test(questionId)) return json({ code: "question_not_found" }, 404, session);
    const sql = database();
    const rows = await sql<Array<{ state: AssessmentState }>>`
      SELECT state FROM java_assessment_sessions
      WHERE id = ${id} AND owner_hash = ${session.ownerHash} AND expires_at > now()`;
    const state = rows[0]?.state;
    if (!state) return json({ code: "session_not_found" }, 404, session);
    const delivered = state.currentId === questionId || state.answers.some((answer) => answer.questionId === questionId);
    const question = delivered ? state.questions.find((item) => item.id === questionId) : null;
    if (!question) return json({ code: "question_not_found" }, 404, session);
    const includeExplanation = new URL(request.url).searchParams.get("review") === "1";
    if (includeExplanation && state.currentId !== null) return json({ code: "assessment_not_complete" }, 409, session);
    const safetyIdentifier = createHash("sha256").update(session.ownerHash).digest("hex").slice(0, 64);
    const translation = await translateAssessmentQuestion(question, includeExplanation, safetyIdentifier);
    return json({ translation }, 200, session);
  } catch (error) {
    console.error("Assessment translation failed", error instanceof Error ? error.name : "unknown_error");
    return json({ code: "translation_unavailable" }, 503, session);
  }
}
