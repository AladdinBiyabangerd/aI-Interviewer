import { del } from "@vercel/blob";

import { cronSecret } from "../../../../lib/server/config";
import { database } from "../../../../lib/server/database";
import { json } from "../../../../lib/server/http";
import { removeProviderFile } from "../../../../lib/server/interview-ai";

export const runtime = "nodejs";
export const maxDuration = 120;

export async function GET(request: Request) {
  if (request.headers.get("authorization") !== `Bearer ${cronSecret()}`) {
    return json({ code: "unauthorized" }, 401);
  }
  const sql = database();
  const preparations = await sql<{ provider_file_id: string | null }[]>`
    SELECT provider_file_id FROM interview_preparations
    WHERE expires_at <= now() AND provider_file_id IS NOT NULL
    LIMIT 100
  `;
  await Promise.all(preparations.map((row) => removeProviderFile(row.provider_file_id)));
  const uploads = await sql<{ blob_url: string }[]>`
    SELECT blob_url FROM interview_cv_uploads
    WHERE expires_at <= now() AND blob_url IS NOT NULL
    LIMIT 100
  `;
  if (uploads.length) await del(uploads.map((row) => row.blob_url));
  const deleted = await sql.begin(async (transaction) => {
    const sessions = await transaction`DELETE FROM interview_practice_sessions WHERE expires_at <= now() RETURNING id`;
    const jobs = await transaction`DELETE FROM interview_preparations WHERE expires_at <= now() RETURNING id`;
    const files = await transaction`DELETE FROM interview_cv_uploads WHERE expires_at <= now() RETURNING id`;
    return { sessions: sessions.length, preparations: jobs.length, uploads: files.length };
  });
  return json({ deleted });
}
