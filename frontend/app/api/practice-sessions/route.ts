import { publicInterviewGuard } from "../../../lib/server/interview-access";
import type {
  InterviewAnalysis,
  PracticeDuration,
  PracticeFocus,
  PracticeMode,
} from "../../../lib/interview-api";
import { retentionDays } from "../../../lib/server/config";
import { database } from "../../../lib/server/database";
import { json } from "../../../lib/server/http";
import { sessionFor } from "../../../lib/server/session";

export const runtime = "nodejs";
export const maxDuration = 30;

type StartInput = {
  preparationId: string;
  mode: PracticeMode;
  focus: PracticeFocus;
  duration: PracticeDuration;
  questionIds: string[];
};

const modes: PracticeMode[] = ["Real Interview", "Practice"];
const focuses: PracticeFocus[] = ["Full Interview", "Technical", "HR / Behavioral", "CV Deep Dive"];
const durations: PracticeDuration[] = ["15 min", "30 min", "45 min"];

function parseInput(value: unknown): StartInput | null {
  if (!value || typeof value !== "object") return null;
  const item = value as Partial<StartInput>;
  if (typeof item.preparationId !== "string"
    || !/^[0-9a-f-]{36}$/i.test(item.preparationId)
    || !modes.includes(item.mode as PracticeMode)
    || !focuses.includes(item.focus as PracticeFocus)
    || !durations.includes(item.duration as PracticeDuration)
    || !Array.isArray(item.questionIds)
    || item.questionIds.length < 1
    || item.questionIds.length > 20
    || item.questionIds.some((id) => typeof id !== "string" || id.length > 128)) {
    return null;
  }
  return item as StartInput;
}

export async function POST(request: Request) {
  const blocked = publicInterviewGuard();
  if (blocked) return blocked;
  const session = sessionFor(request);
  let input: StartInput | null = null;
  try {
    input = parseInput(await request.json());
  } catch {
    return json({ code: "invalid_json" }, 400, session);
  }
  if (!input) return json({ code: "invalid_request" }, 400, session);

  const sql = database();
  const preparations = await sql<{ analysis: InterviewAnalysis }[]>`
    SELECT analysis FROM interview_preparations
    WHERE id = ${input.preparationId} AND owner_hash = ${session.ownerHash}
      AND status = 'completed' AND expires_at > now()
  `;
  const analysis = preparations[0]?.analysis;
  if (!analysis) return json({ code: "preparation_not_found" }, 404, session);
  const available = new Set(analysis.questions.map((question) => question.id));
  const uniqueIds = [...new Set(input.questionIds)];
  if (uniqueIds.length !== input.questionIds.length || uniqueIds.some((id) => !available.has(id))) {
    return json({ code: "invalid_questions" }, 400, session);
  }

  const sessionId = crypto.randomUUID();
  const minutes = Number.parseInt(input.duration, 10);
  await sql`
    INSERT INTO interview_practice_sessions (
      id, preparation_id, owner_hash, mode, focus, duration_minutes, question_ids, expires_at
    ) VALUES (
      ${sessionId}, ${input.preparationId}, ${session.ownerHash}, ${input.mode}, ${input.focus},
      ${minutes}, ${sql.json(uniqueIds)}, now() + (${retentionDays()} * interval '1 day')
    )
  `;
  return json({ sessionId }, 201, session);
}
