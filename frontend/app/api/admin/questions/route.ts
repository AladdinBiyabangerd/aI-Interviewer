import { AdminQuestionError } from "../../../../lib/admin-question";
import { adminGuard } from "../../../../lib/server/admin-access";
import { editQuestion, insertDrafts, parseAdminQuestion, readAdminQuestions, setQuestionStatus, validQuestionTarget } from "../../../../lib/server/admin-questions";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function body(request: Request): Promise<Record<string, unknown>> {
  if (!request.headers.get("content-type")?.startsWith("application/json")) throw new AdminQuestionError("invalid_content_type", 415);
  const text = await request.text();
  if (Buffer.byteLength(text, "utf8") > 20_000) throw new AdminQuestionError("request_too_large", 413);
  try {
    const result: unknown = JSON.parse(text);
    if (!result || typeof result !== "object" || Array.isArray(result)) throw new Error();
    return result as Record<string, unknown>;
  } catch { throw new AdminQuestionError("invalid_json"); }
}

function failure(error: unknown): Response {
  if (error instanceof AdminQuestionError) return Response.json({ code: error.code }, { status: error.status, headers: { "Cache-Control": "no-store" } });
  console.error("Admin questions failed", error instanceof Error ? error.name : "unknown_error");
  return Response.json({ code: "admin_questions_unavailable" }, { status: 503, headers: { "Cache-Control": "no-store" } });
}

export async function GET(request: Request): Promise<Response> {
  const denied = await adminGuard(request);
  if (denied) return denied;
  try { return Response.json({ questions: await readAdminQuestions() }, { headers: { "Cache-Control": "no-store" } }); }
  catch (error) { return failure(error); }
}

export async function POST(request: Request): Promise<Response> {
  const denied = await adminGuard(request, true);
  if (denied) return denied;
  try {
    const input = parseAdminQuestion((await body(request)).question);
    const [question] = await insertDrafts([input], "manual");
    return Response.json({ question }, { status: 201, headers: { "Cache-Control": "no-store" } });
  } catch (error) { return failure(error); }
}

export async function PATCH(request: Request): Promise<Response> {
  const denied = await adminGuard(request, true);
  if (denied) return denied;
  try {
    const input = await body(request);
    if (!validQuestionTarget(input.id, input.version)) throw new AdminQuestionError("invalid_question_target");
    const id = input.id as string;
    const version = input.version as number;
    const question = input.action === "edit" ? await editQuestion(id, version, input.question)
      : input.action === "publish" || input.action === "retire"
        ? await setQuestionStatus(id, version, input.action === "publish" ? "published" : "retired")
        : null;
    if (!question) throw new AdminQuestionError("invalid_action");
    return Response.json({ question }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) { return failure(error); }
}
