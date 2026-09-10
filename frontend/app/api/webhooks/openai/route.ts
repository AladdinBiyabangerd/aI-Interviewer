import { publicInterviewGuard } from "../../../../lib/server/interview-access";
import { preparationByProviderResponse, refreshPreparation } from "../../../../lib/server/analysis-jobs";
import { json } from "../../../../lib/server/http";
import { unwrapOpenAIWebhook } from "../../../../lib/server/interview-ai";

export const runtime = "nodejs";
export const maxDuration = 120;

export async function POST(request: Request) {
  const blocked = publicInterviewGuard();
  if (blocked) return blocked;
  let event: { type: string; data: { id: string } };
  try {
    event = await unwrapOpenAIWebhook(await request.text(), request.headers);
  } catch (error) {
    console.error("OpenAI webhook verification failed", error instanceof Error ? error.message : "unknown_error");
    return json({ code: "invalid_signature" }, 400);
  }
  if (!event.type.startsWith("response.")) return json({ received: true });
  const row = await preparationByProviderResponse(event.data.id);
  if (!row) return json({ received: true });
  try {
    await refreshPreparation(row);
  } catch (error) {
    console.error("OpenAI webhook reconciliation failed", error instanceof Error ? error.message : "unknown_error");
    return json({ code: "reconciliation_failed" }, 500);
  }
  return json({ received: true });
}
