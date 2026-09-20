import "server-only";

import { createHash } from "node:crypto";
import { AdminQuestionError, bankQuestion, parseQuestionInput, type QuestionInput } from "../admin-question";
import type { BankQuestion } from "./assessment-bank";
import { validateBank } from "./assessment-bank-validation";
import { database } from "./database";

export type AdminQuestionRow = { id: string; version: number; status: BankQuestion["status"]; question: BankQuestion; created_at: string };

function contentHash(question: BankQuestion): string {
  const content: Partial<BankQuestion> = { ...question };
  delete content.status;
  return createHash("sha256").update(JSON.stringify(content)).digest("hex");
}

export async function readAdminQuestions(): Promise<AdminQuestionRow[]> {
  return database()<AdminQuestionRow[]>`
    SELECT id, version, status, question, created_at
    FROM java_question_bank
    WHERE id LIKE 'admin-%'
    ORDER BY created_at DESC, id DESC, version DESC LIMIT 100`;
}

export async function insertDrafts(inputs: QuestionInput[], origin: "manual" | "ai"): Promise<AdminQuestionRow[]> {
  const questions = inputs.map((input) => bankQuestion(input, origin));
  validateBank(questions);
  const sql = database();
  return sql.begin(async (tx) => {
    const result: AdminQuestionRow[] = [];
    for (const question of questions) {
      const rows = await tx<AdminQuestionRow[]>`
        INSERT INTO java_question_bank (id, version, status, content_hash, question)
        VALUES (${question.id}, ${question.version}, 'draft', ${contentHash(question)}, ${tx.json(question)})
        RETURNING id, version, status, question, created_at`;
      result.push(rows[0]);
    }
    return result;
  });
}

export async function editQuestion(id: string, version: number, raw: unknown): Promise<AdminQuestionRow> {
  const input = parseQuestionInput(raw);
  const sql = database();
  return sql.begin(async (tx) => {
    const rows = await tx<AdminQuestionRow[]>`
      SELECT id, version, status, question, created_at FROM java_question_bank
      WHERE id = ${id} AND version = ${version} FOR UPDATE`;
    const existing = rows[0];
    if (!existing || !id.startsWith("admin-")) throw new AdminQuestionError("question_not_found", 404);
    if (existing.status === "retired") throw new AdminQuestionError("question_retired", 409);
    const nextVersion = existing.status === "published" ? version + 1 : version;
    const question = bankQuestion(input, existing.question.editorialOrigin ?? "manual", id, nextVersion);
    validateBank([question]);
    if (existing.status === "published") {
      const later = await tx`SELECT 1 FROM java_question_bank WHERE id = ${id} AND version >= ${nextVersion} LIMIT 1`;
      if (later.length) throw new AdminQuestionError("newer_revision_exists", 409);
      const created = await tx<AdminQuestionRow[]>`
        INSERT INTO java_question_bank (id, version, status, content_hash, question)
        VALUES (${id}, ${nextVersion}, 'draft', ${contentHash(question)}, ${tx.json(question)})
        RETURNING id, version, status, question, created_at`;
      return created[0];
    }
    const updated = await tx<AdminQuestionRow[]>`
      UPDATE java_question_bank SET content_hash = ${contentHash(question)}, question = ${tx.json(question)}
      WHERE id = ${id} AND version = ${version}
      RETURNING id, version, status, question, created_at`;
    return updated[0];
  });
}

export async function setQuestionStatus(id: string, version: number, status: "published" | "retired"): Promise<AdminQuestionRow> {
  const sql = database();
  return sql.begin(async (tx) => {
    const rows = await tx<AdminQuestionRow[]>`
      SELECT id, version, status, question, created_at FROM java_question_bank
      WHERE id = ${id} AND version = ${version} FOR UPDATE`;
    const current = rows[0];
    if (!current || !id.startsWith("admin-")) throw new AdminQuestionError("question_not_found", 404);
    if (status === "published") {
      if (current.status !== "draft") throw new AdminQuestionError("question_not_draft", 409);
      validateBank([current.question]);
      const newer = await tx`SELECT 1 FROM java_question_bank WHERE id = ${id} AND version > ${version} LIMIT 1`;
      if (newer.length) throw new AdminQuestionError("newer_revision_exists", 409);
      // Keep one public revision for this ID. Existing assessment snapshots stay immutable.
      await tx`UPDATE java_question_bank SET status = 'retired' WHERE id = ${id} AND status = 'published'`;
    } else if (current.status === "retired") {
      throw new AdminQuestionError("question_retired", 409);
    }
    const updated = await tx<AdminQuestionRow[]>`
      UPDATE java_question_bank SET status = ${status} WHERE id = ${id} AND version = ${version}
      RETURNING id, version, status, question, created_at`;
    return updated[0];
  });
}

export async function recentAiDraftCount(): Promise<number> {
  const rows = await database()<Array<{ count: number }>>`
    SELECT count(*)::int AS count FROM java_question_bank
    WHERE question->>'editorialOrigin' = 'ai' AND created_at > now() - interval '1 hour'`;
  return rows[0].count;
}

export function parseAdminQuestion(value: unknown): QuestionInput { return parseQuestionInput(value); }

export function validQuestionTarget(id: unknown, version: unknown): id is string {
  return typeof id === "string" && /^admin-[0-9a-f-]{36}$/.test(id)
    && Number.isInteger(version) && (version as number) > 0 && (version as number) <= 1000;
}
