import { publicInterviewGuard } from "../../../../lib/server/interview-access";
import type { InterviewDetails, InterviewLanguage, InterviewStage, Seniority } from "../../../../lib/interview-api";
import { analysisLimit, retentionDays } from "../../../../lib/server/config";
import { database } from "../../../../lib/server/database";
import { json } from "../../../../lib/server/http";
import {
  removeProviderFile,
  startCvReview,
  startResearch,
  uploadProviderFile,
} from "../../../../lib/server/interview-ai";
import { opaqueSafetyIdentifier, sessionFor } from "../../../../lib/server/session";

export const runtime = "nodejs";
export const maxDuration = 60;

type UnknownRecord = Record<string, unknown>;

const seniorities: Seniority[] = ["Not specified", "Intern", "Junior", "Mid-level", "Senior", "Lead"];
const stages: InterviewStage[] = [
  "Not sure", "HR / Recruiter", "Technical Interview", "Coding Interview",
  "System Design", "Hiring Manager", "Final Interview",
];
const languages: InterviewLanguage[] = ["English", "Azerbaijani"];

function isRecord(value: unknown): value is UnknownRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function text(value: unknown, maximum: number): string | null {
  if (typeof value !== "string") return null;
  const normalized = value.trim();
  return normalized && normalized.length <= maximum ? normalized : null;
}

function optionalUrl(value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  const raw = text(value, 2_048);
  if (!raw) throw new Error("invalid_job_url");
  const url = new URL(raw);
  if (url.protocol !== "https:" && url.protocol !== "http:") throw new Error("invalid_job_url");
  return url.href;
}

function parseInput(value: unknown): InterviewDetails | null {
  if (!isRecord(value)) return null;
  const company = text(value.company, 120);
  const role = text(value.role, 160);
  const jobDescription = text(value.jobDescription, 20_000);
  if (!company || !role || !jobDescription || jobDescription.length < 40) return null;
  const seniority = seniorities.includes(value.seniority as Seniority) ? value.seniority as Seniority : null;
  const stage = stages.includes(value.stage as InterviewStage) ? value.stage as InterviewStage : null;
  const language = languages.includes(value.language as InterviewLanguage) ? value.language as InterviewLanguage : null;
  if (!seniority || !stage || !language) return null;
  const cvUploadId = value.cvUploadId === null ? null : text(value.cvUploadId, 64);
  const cvFileName = value.cvFileName === null ? null : text(value.cvFileName, 240);
  const cvFileType = value.cvFileType === null ? null : text(value.cvFileType, 128);
  const cvFileSize = value.cvFileSize === null ? null : Number(value.cvFileSize);
  const anyCv = Boolean(cvUploadId || cvFileName || cvFileType || cvFileSize);
  const validCv = !anyCv || (
    Boolean(cvUploadId && /^[0-9a-f-]{36}$/i.test(cvUploadId))
    && Boolean(cvFileName)
    && ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"].includes(cvFileType ?? "")
    && Number.isSafeInteger(cvFileSize) && Number(cvFileSize) > 0 && Number(cvFileSize) <= 10 * 1024 * 1024
  );
  if (!validCv) return null;
  try {
    return {
      company,
      role,
      jobDescription,
      jobUrl: optionalUrl(value.jobUrl),
      seniority,
      stage,
      language,
      cvUploadId: anyCv ? cvUploadId : null,
      cvFileName: anyCv ? cvFileName : null,
      cvFileType: anyCv ? cvFileType : null,
      cvFileSize: anyCv ? Number(cvFileSize) : null,
    };
  } catch {
    return null;
  }
}

export async function POST(request: Request) {
  const blocked = publicInterviewGuard();
  if (blocked) return blocked;
  const session = sessionFor(request);
  let details: InterviewDetails | null = null;
  try {
    details = parseInput(await request.json());
  } catch {
    return json({ code: "invalid_json" }, 400, session);
  }
  if (!details) return json({ code: "invalid_request" }, 400, session);

  const sql = database();
  let upload: { id: string; pathname: string; file_name: string; content_type: string } | null = null;
  if (details.cvUploadId) {
    const uploads = await sql<{ id: string; pathname: string; file_name: string; content_type: string }[]>`
      SELECT id, pathname, file_name, content_type
      FROM interview_cv_uploads
      WHERE id = ${details.cvUploadId} AND owner_hash = ${session.ownerHash}
        AND status = 'ready' AND expires_at > now()
    `;
    upload = uploads[0] ?? null;
    if (!upload?.pathname) return json({ code: "cv_not_ready" }, 409, session);
  }

  const preparationId = crypto.randomUUID();
  try {
    await sql.begin(async (transaction) => {
      await transaction`SELECT pg_advisory_xact_lock(hashtextextended(${session.requesterHash}, 0))`;
      const recent = await transaction<{ count: number }[]>`
        SELECT count(*)::int AS count FROM interview_preparations
        WHERE requester_hash = ${session.requesterHash} AND created_at > now() - interval '10 minutes'
      `;
      if ((recent[0]?.count ?? 0) >= analysisLimit()) throw new Error("rate_limited");
      await transaction`
        INSERT INTO interview_preparations (
          id, owner_hash, requester_hash, status, input, cv_upload_id, expires_at
        ) VALUES (
          ${preparationId}, ${session.ownerHash}, ${session.requesterHash}, 'queued',
          ${transaction.json(details)}, ${details.cvUploadId},
          now() + (${retentionDays()} * interval '1 day')
        )
      `;
    });
  } catch (error) {
    if (error instanceof Error && error.message === "rate_limited") {
      return json({ code: "rate_limited" }, 429, session, { "Retry-After": "600" });
    }
    console.error("Analysis job creation failed", error instanceof Error ? error.message : "unknown_error");
    return json({ code: "database_unavailable" }, 503, session);
  }

  let providerFileId: string | null = null;
  let researchResponseId: string | null = null;
  try {
    if (upload) {
      providerFileId = await uploadProviderFile(upload.pathname, upload.file_name, upload.content_type);
    }
    const safetyIdentifier = opaqueSafetyIdentifier(session);
    const [researchId, cvId] = await Promise.all([
      startResearch(details, safetyIdentifier),
      providerFileId ? startCvReview(details, providerFileId, safetyIdentifier) : Promise.resolve(null),
    ]);
    researchResponseId = researchId;
    await sql`
      UPDATE interview_preparations
      SET status = 'in_progress', research_response_id = ${researchId}, cv_response_id = ${cvId},
          provider_file_id = ${providerFileId}, updated_at = now()
      WHERE id = ${preparationId} AND owner_hash = ${session.ownerHash}
    `;
    return json({ jobId: preparationId, status: "in_progress" }, 202, session);
  } catch (error) {
    if (researchResponseId) {
      // The response is left to OpenAI's short background retention window; no user data is returned.
    }
    await removeProviderFile(providerFileId);
    await sql`
      UPDATE interview_preparations
      SET status = 'failed', error_code = 'analysis_start_failed', updated_at = now()
      WHERE id = ${preparationId} AND owner_hash = ${session.ownerHash}
    `;
    console.error("Analysis job start failed", error instanceof Error ? error.message : "unknown_error");
    return json({ code: "analysis_start_failed" }, 502, session);
  }
}
