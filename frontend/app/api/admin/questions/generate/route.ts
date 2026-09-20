import { AdminQuestionError } from "../../../../../lib/admin-question";
import { adminGuard } from "../../../../../lib/server/admin-access";
import { generateQuestions, parseGenerationRequest } from "../../../../../lib/server/admin-question-ai";
import { insertDrafts, recentAiDraftCount } from "../../../../../lib/server/admin-questions";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const denied = await adminGuard(request, true);
  if (denied) return denied;
  try {
    if (!request.headers.get("content-type")?.startsWith("application/json")) throw new AdminQuestionError("invalid_content_type", 415);
    const text = await request.text();
    if (Buffer.byteLength(text, "utf8") > 15_000) throw new AdminQuestionError("request_too_large", 413);
    let raw: unknown;
    try { raw = JSON.parse(text); } catch { throw new AdminQuestionError("invalid_json"); }
    const input = parseGenerationRequest(raw);
    if (await recentAiDraftCount() + input.count > 30) throw new AdminQuestionError("ai_rate_limited", 429);
    const generated = await generateQuestions(input);
    const questions = await insertDrafts(generated.questions, "ai");
    return Response.json({ reply: generated.reply, questions }, {
      status: 201, headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    if (error instanceof AdminQuestionError) return Response.json({ code: error.code }, {
      status: error.status, headers: { "Cache-Control": "no-store" },
    });
    console.error("Admin generation failed", error instanceof Error ? error.name : "unknown_error");
    return Response.json({ code: "ai_generation_unavailable" }, {
      status: 503, headers: { "Cache-Control": "no-store" },
    });
  }
}
