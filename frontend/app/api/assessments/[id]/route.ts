import { assessmentRequest } from "../../../../lib/server/assessment-store";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ id: string }> };
export async function GET(request: Request, context: Context) {
  return assessmentRequest(request, (await context.params).id);
}
export async function POST(request: Request, context: Context) {
  return assessmentRequest(request, (await context.params).id);
}
