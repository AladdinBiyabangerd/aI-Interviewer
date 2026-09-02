import type { InterviewAnalysis } from "../../../../lib/interview-api";
import { database } from "../../../../lib/server/database";
import { json } from "../../../../lib/server/http";
import { sessionFor } from "../../../../lib/server/session";

export const runtime = "nodejs";
export const maxDuration = 30;
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const session = sessionFor(request);
  const sql = database();
  const rows = await sql<{ analysis: InterviewAnalysis }[]>`
    SELECT analysis FROM interview_preparations
    WHERE owner_hash = ${session.ownerHash} AND status = 'completed'
      AND analysis IS NOT NULL AND expires_at > now()
    ORDER BY created_at DESC LIMIT 1
  `;
  return json({ analysis: rows[0]?.analysis ?? null }, 200, session);
}
