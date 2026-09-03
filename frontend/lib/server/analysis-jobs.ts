import "server-only";

import type { InterviewAnalysis, InterviewDetails } from "../interview-api";
import { database } from "./database";
import {
  buildAnalysis,
  removeProviderFile,
  retrieveResponse,
  terminalResponseStatus,
} from "./interview-ai";

export type PreparationJobRow = {
  id: string;
  owner_hash: string;
  created_at: Date | string;
  status: "queued" | "in_progress" | "completed" | "failed";
  input: InterviewDetails;
  analysis: InterviewAnalysis | null;
  research_response_id: string | null;
  cv_response_id: string | null;
  provider_file_id: string | null;
  cv_upload_id: string | null;
};

export async function preparationById(id: string, ownerHash?: string): Promise<PreparationJobRow | null> {
  const sql = database();
  const rows = ownerHash
    ? await sql<PreparationJobRow[]>`
        SELECT id, owner_hash, created_at, status, input, analysis, research_response_id,
               cv_response_id, provider_file_id, cv_upload_id
        FROM interview_preparations
        WHERE id = ${id} AND owner_hash = ${ownerHash} AND expires_at > now()
      `
    : await sql<PreparationJobRow[]>`
        SELECT id, owner_hash, created_at, status, input, analysis, research_response_id,
               cv_response_id, provider_file_id, cv_upload_id
        FROM interview_preparations
        WHERE id = ${id} AND expires_at > now()
      `;
  return rows[0] ?? null;
}

export async function preparationByProviderResponse(id: string): Promise<PreparationJobRow | null> {
  const sql = database();
  const rows = await sql<PreparationJobRow[]>`
    SELECT id, owner_hash, created_at, status, input, analysis, research_response_id,
           cv_response_id, provider_file_id, cv_upload_id
    FROM interview_preparations
    WHERE (research_response_id = ${id} OR cv_response_id = ${id}) AND expires_at > now()
    ORDER BY created_at DESC LIMIT 1
  `;
  return rows[0] ?? null;
}

export async function refreshPreparation(row: PreparationJobRow): Promise<{
  status: "queued" | "in_progress" | "completed" | "failed";
  analysis?: InterviewAnalysis;
  phase?: "researching" | "reviewing_cv";
}> {
  if (row.status === "completed" && row.analysis) return { status: "completed", analysis: row.analysis };
  if (row.status === "failed") return { status: "failed" };
  if (!row.research_response_id) return { status: row.status };

  const [research, cv] = await Promise.all([
    retrieveResponse(row.research_response_id),
    row.cv_response_id ? retrieveResponse(row.cv_response_id) : Promise.resolve(null),
  ]);
  const responses = [research, cv].filter((item) => item !== null);
  const failed = responses.some((response) => terminalResponseStatus(response.status ?? "unknown") && response.status !== "completed");
  const sql = database();
  if (failed) {
    await removeProviderFile(row.provider_file_id);
    await sql`
      UPDATE interview_preparations
      SET status = 'failed', error_code = 'analysis_provider_failed', provider_file_id = NULL,
          updated_at = now()
      WHERE id = ${row.id} AND status <> 'completed'
    `;
    return { status: "failed" };
  }
  if (responses.some((response) => response.status !== "completed")) {
    const cvPending = cv !== null && cv.status !== "completed";
    return { status: "in_progress", phase: research.status === "completed" && cvPending ? "reviewing_cv" : "researching" };
  }

  const analysis = buildAnalysis(
    row.id,
    new Date(row.created_at).toISOString(),
    row.input,
    research,
    cv,
  );
  await sql.begin(async (transaction) => {
    await transaction`
      UPDATE interview_preparations
      SET status = 'completed', analysis = ${transaction.json(analysis)}, provider_file_id = NULL,
          error_code = NULL, updated_at = now()
      WHERE id = ${row.id} AND status <> 'failed'
    `;
    if (row.cv_upload_id) {
      await transaction`
        UPDATE interview_cv_uploads SET status = 'consumed', updated_at = now()
        WHERE id = ${row.cv_upload_id} AND owner_hash = ${row.owner_hash}
      `;
    }
  });
  await removeProviderFile(row.provider_file_id);
  return { status: "completed", analysis };
}
