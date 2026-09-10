import { publicInterviewGuard } from "../../../../../lib/server/interview-access";
import { preparationById, refreshPreparation } from "../../../../../lib/server/analysis-jobs";
import { json } from "../../../../../lib/server/http";
import { sessionFor } from "../../../../../lib/server/session";

export const runtime = "nodejs";
export const maxDuration = 60;
export const dynamic = "force-dynamic";

function uuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

export async function GET(request: Request, context: { params: Promise<{ jobId: string }> }) {
  const blocked = publicInterviewGuard();
  if (blocked) return blocked;
  const session = sessionFor(request);
  const { jobId } = await context.params;
  if (!uuid(jobId)) return json({ code: "not_found" }, 404, session);
  const row = await preparationById(jobId, session.ownerHash);
  if (!row) return json({ code: "not_found" }, 404, session);
  try {
    return json(await refreshPreparation(row), 200, session);
  } catch (error) {
    console.error("Analysis status refresh failed", error instanceof Error ? error.message : "unknown_error");
    return json({ code: "analysis_status_unavailable" }, 502, session);
  }
}
