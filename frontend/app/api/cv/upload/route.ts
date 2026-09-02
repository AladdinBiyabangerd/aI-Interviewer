import { head } from "@vercel/blob";
import { handleUpload, type HandleUploadBody } from "@vercel/blob/client";

import { retentionDays } from "../../../../lib/server/config";
import { database } from "../../../../lib/server/database";
import { json } from "../../../../lib/server/http";
import { sessionFor } from "../../../../lib/server/session";

export const runtime = "nodejs";
export const maxDuration = 30;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const PDF = "application/pdf";
const DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

function uploadIdFrom(payload: string | null): string {
  if (!payload || payload.length > 200) throw new Error("invalid_upload_ticket");
  const parsed: unknown = JSON.parse(payload);
  if (!parsed || typeof parsed !== "object" || !("uploadId" in parsed)) throw new Error("invalid_upload_ticket");
  const uploadId = (parsed as { uploadId?: unknown }).uploadId;
  if (typeof uploadId !== "string" || !UUID.test(uploadId)) throw new Error("invalid_upload_ticket");
  return uploadId;
}

function inferredType(pathname: string): string {
  if (pathname.toLowerCase().endsWith(".pdf")) return PDF;
  if (pathname.toLowerCase().endsWith(".docx")) return DOCX;
  throw new Error("invalid_file_type");
}

export async function POST(request: Request) {
  const session = sessionFor(request);
  let body: HandleUploadBody;
  try {
    body = await request.json() as HandleUploadBody;
  } catch {
    return json({ code: "invalid_json" }, 400, session);
  }

  try {
    const result = await handleUpload({
      request,
      body,
      onBeforeGenerateToken: async (pathname, clientPayload) => {
        const uploadId = uploadIdFrom(clientPayload);
        if (!pathname.startsWith(`cv/${uploadId}/`) || pathname.length > 1024) {
          throw new Error("invalid_upload_path");
        }
        const contentType = inferredType(pathname);
        const fileName = decodeURIComponent(pathname.split("/").at(-1) ?? "cv").slice(0, 240);
        const sql = database();
        await sql`
          INSERT INTO interview_cv_uploads (
            id, owner_hash, file_name, content_type, status, expires_at
          ) VALUES (
            ${uploadId}, ${session.ownerHash}, ${fileName}, ${contentType}, 'pending',
            now() + (${retentionDays()} * interval '1 day')
          )
          ON CONFLICT (id) DO NOTHING
        `;
        const owned = await sql`
          SELECT id FROM interview_cv_uploads
          WHERE id = ${uploadId} AND owner_hash = ${session.ownerHash} AND status = 'pending'
        `;
        if (!owned.length) throw new Error("upload_ticket_conflict");
        return {
          allowedContentTypes: [PDF, DOCX],
          maximumSizeInBytes: 10 * 1024 * 1024,
          validUntil: Date.now() + 10 * 60 * 1000,
          addRandomSuffix: true,
          allowOverwrite: false,
          tokenPayload: JSON.stringify({ uploadId, ownerHash: session.ownerHash }),
        };
      },
      onUploadCompleted: async ({ blob, tokenPayload }) => {
        const token = typeof tokenPayload === "string" ? JSON.parse(tokenPayload) as unknown : null;
        if (!token || typeof token !== "object") throw new Error("invalid_upload_callback");
        const { uploadId, ownerHash } = token as { uploadId?: unknown; ownerHash?: unknown };
        if (typeof uploadId !== "string" || !UUID.test(uploadId)
          || typeof ownerHash !== "string" || !/^[0-9a-f]{64}$/.test(ownerHash)) {
          throw new Error("invalid_upload_callback");
        }
        const metadata = await head(blob.pathname);
        if (metadata.size < 1 || metadata.size > 10 * 1024 * 1024) throw new Error("invalid_upload_size");
        const sql = database();
        const updated = await sql`
          UPDATE interview_cv_uploads
          SET pathname = ${blob.pathname}, blob_url = ${blob.url}, content_type = ${blob.contentType},
              size_bytes = ${metadata.size}, status = 'ready', updated_at = now()
          WHERE id = ${uploadId} AND owner_hash = ${ownerHash} AND status = 'pending'
          RETURNING id
        `;
        if (!updated.length) throw new Error("upload_ticket_missing");
      },
    });
    return json(result, 200, session);
  } catch (error) {
    console.error("CV upload handshake failed", error instanceof Error ? error.message : "unknown_error");
    return json({ code: "cv_upload_failed" }, 400, session);
  }
}
