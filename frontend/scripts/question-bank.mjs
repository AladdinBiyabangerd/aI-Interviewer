import { createHash } from "node:crypto";
import { readFile, stat } from "node:fs/promises";
import postgres from "postgres";
import { questionBank } from "../lib/server/assessment-bank.ts";
import { validateBank } from "../lib/server/assessment-bank-validation.ts";

const [command, argument, versionText] = process.argv.slice(2);
const commands = ["validate", "seed", "import", "list", "review", "publish", "retire", "resolve", "stage", "staged", "source-rights"];
if (!commands.includes(command)) {
  console.error("Usage: npm run bank -- validate|seed|import <file.json>|list|review|publish <id> <version>|retire <id> <version>|resolve <id> <version>|stage <extraction.json>|staged|source-rights <batch-id> <cleared|rejected>");
  process.exit(1);
}
let sql;
try {
  const bank = command === "import" ? JSON.parse(await readFile(argument, "utf8")) : questionBank;
  if (!["stage", "staged", "source-rights"].includes(command)) validateBank(bank);
  if (command === "validate") {
    console.log(`Validated ${bank.length} original questions across ${new Set(bank.map((q) => q.topic)).size} topics.`);
  } else {
    if (!process.env.DATABASE_URL) throw new Error("DATABASE_URL is required");
    sql = postgres(process.env.DATABASE_URL, { max: 1, prepare: false });
    if (command === "stage") {
      if (!argument || (await stat(argument)).size > 50 * 1024 * 1024) throw new Error("A bounded extraction JSON file is required (maximum 50 MiB)");
      const raw = await readFile(argument);
      const artifactHash = createHash("sha256").update(raw).digest("hex");
      const document = JSON.parse(raw.toString("utf8"));
      const source = document?.source;
      if (document?.schema_version !== 1 || typeof document.parser_release !== "string" || !/^[a-z0-9-]{3,64}$/.test(document.parser_release)
        || document.rights_status !== "unverified" || !["ready", "review_required", "failed"].includes(document.status)
        || !source || typeof source.file_name !== "string" || !source.file_name.trim() || source.file_name.length > 255
        || typeof source.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(source.sha256)
        || typeof source.title !== "string" || !source.title.trim() || source.title.length > 500
        || (source.authors !== null && source.authors !== undefined && (typeof source.authors !== "string" || !source.authors.trim() || source.authors.length > 500))
        || (source.publisher !== null && source.publisher !== undefined && (typeof source.publisher !== "string" || !source.publisher.trim() || source.publisher.length > 200))
        || (source.publication_year !== null && source.publication_year !== undefined && (!Number.isInteger(source.publication_year) || source.publication_year < 1900 || source.publication_year > new Date().getUTCFullYear() + 1))
        || (source.reference_url !== null && source.reference_url !== undefined && (typeof source.reference_url !== "string" || source.reference_url.length > 2048 || !/^https:\/\//.test(source.reference_url)))
        || !Number.isInteger(source.page_count) || source.page_count < 1
        || !Array.isArray(document.candidates) || document.candidates.length > 5000
        || document.question_count !== document.candidates.length
        || document.answer_count !== document.candidates.filter((q) => q.correct !== null).length
        || !document.report || typeof document.report !== "object" || Array.isArray(document.report)) throw new Error("Invalid extraction document");
      const keys = new Set();
      for (const q of document.candidates) {
        const optionIds = Array.isArray(q?.options) ? q.options.map((option) => option?.id) : [];
        if (!q || typeof q.source_question_key !== "string" || !/^[a-z0-9-]{3,160}$/.test(q.source_question_key) || keys.has(q.source_question_key)
          || (q.chapter_number !== null && (!Number.isInteger(q.chapter_number) || q.chapter_number < 1))
          || typeof q.chapter_title !== "string" || !q.chapter_title.trim() || q.chapter_title.length > 300
          || !Number.isInteger(q.question_number) || q.question_number < 1
          || !Number.isInteger(q.page_start) || !Number.isInteger(q.page_end) || q.page_start < 1 || q.page_end < q.page_start || q.page_end > source.page_count
          || typeof q.prompt !== "string" || !q.prompt.trim() || q.prompt.length > 20000
          || !Array.isArray(q.options) || q.options.length < 2 || q.options.length > 8 || q.options.some((o) => !o || typeof o.id !== "string" || !/^[A-H]$/.test(o.id) || typeof o.text !== "string" || !o.text.trim() || o.text.length > 12000)
          || optionIds.length !== new Set(optionIds).size
          || (q.correct !== null && (!Array.isArray(q.correct) || !q.correct.length || q.correct.length !== new Set(q.correct).size || q.correct.some((id) => typeof id !== "string" || !optionIds.includes(id))))
          || (q.explanation !== null && (typeof q.explanation !== "string" || q.explanation.length > 60000))
          || typeof q.normalized_hash !== "string" || !/^[0-9a-f]{64}$/.test(q.normalized_hash)
          || !["complete", "needs_answer", "needs_review"].includes(q.parse_status)
          || !Array.isArray(q.issue_codes) || q.issue_codes.length !== new Set(q.issue_codes).size || q.issue_codes.some((issue) => typeof issue !== "string" || !/^[a-z0-9_]{3,64}$/.test(issue))
          || (q.correct === null) !== (q.parse_status === "needs_answer")
          || (q.parse_status === "needs_answer" && !q.issue_codes.includes("missing_answer"))
          || (q.parse_status === "complete" && q.issue_codes.length !== 0)
          || (q.parse_status === "needs_review" && q.issue_codes.length === 0)) throw new Error(`Invalid extraction candidate: ${q?.source_question_key ?? "unknown"}`);
        keys.add(q.source_question_key);
      }
      const expectedStatus = document.candidates.some((q) => q.parse_status !== "complete") ? "review_required" : "ready";
      if (document.status !== expectedStatus) throw new Error("Extraction status does not match candidate review states");
      const batchId = await sql.begin(async (tx) => {
        const existing = await tx`SELECT id, question_count, answer_count, report FROM java_question_import_batches WHERE source_sha256 = ${source.sha256} AND parser_release = ${document.parser_release}`;
        if (existing[0]) {
          if (existing[0].question_count !== document.question_count || existing[0].answer_count !== document.answer_count || existing[0].report?.artifact_sha256 !== artifactHash) throw new Error("Extraction changed without a parser release bump");
          return existing[0].id;
        }
        const report = { ...document.report, artifact_sha256: artifactHash };
        const rows = await tx`INSERT INTO java_question_import_batches (source_sha256, file_name, source_title, authors, publisher, publication_year, reference_url, parser_release, rights_status, status, page_count, question_count, answer_count, report)
          VALUES (${source.sha256}, ${source.file_name}, ${source.title}, ${source.authors ?? null}, ${source.publisher ?? null}, ${source.publication_year ?? null}, ${source.reference_url ?? null}, ${document.parser_release}, 'unverified', ${document.status}, ${source.page_count}, ${document.question_count}, ${document.answer_count}, ${tx.json(report)}) RETURNING id`;
        const id = rows[0].id;
        // Pipeline bounded chunks on the transaction's reserved connection. This keeps
        // large books fast on a remote database without building one oversized query.
        for (let offset = 0; offset < document.candidates.length; offset += 100) {
          await Promise.all(document.candidates.slice(offset, offset + 100).map((q) =>
            tx`INSERT INTO java_question_import_candidates (batch_id, source_question_key, chapter_number, chapter_title, question_number, page_start, page_end, prompt, options, correct, explanation, normalized_hash, parse_status, issue_codes)
              VALUES (${id}, ${q.source_question_key}, ${q.chapter_number}, ${q.chapter_title}, ${q.question_number}, ${q.page_start}, ${q.page_end}, ${q.prompt}, ${tx.json(q.options)}, ${q.correct === null ? null : tx.json(q.correct)}, ${q.explanation}, ${q.normalized_hash}, ${q.parse_status}, ${tx.json(q.issue_codes)})`,
          ));
        }
        return id;
      });
      console.log(JSON.stringify({ batchId, sourceSha256: source.sha256, status: document.status, rightsStatus: "unverified", questionCount: document.question_count, answerCount: document.answer_count }));
    } else if (command === "staged") {
      const rows = await sql`SELECT id, source_title, file_name, source_sha256, parser_release, rights_status, status, page_count, question_count, answer_count, report, created_at FROM java_question_import_batches ORDER BY created_at DESC`;
      console.log(JSON.stringify(rows, null, 2));
    } else if (command === "source-rights") {
      if (!/^[0-9a-f-]{36}$/i.test(argument ?? "") || !["cleared", "rejected"].includes(versionText)) throw new Error("Exact batch UUID and rights status (cleared or rejected) are required");
      const rows = await sql`UPDATE java_question_import_batches SET rights_status = ${versionText} WHERE id = ${argument} RETURNING id`;
      if (!rows.length) throw new Error("Import batch not found");
      console.log(`source-rights: ${argument} ${versionText}`);
    } else if (command === "seed" || command === "import") {
      await sql.begin(async (tx) => {
        for (const q of bank) {
          // Status is editorial workflow state, not question content. Initial inserts
          // always enter draft. Re-running an import never re-publishes retired items.
          const content = { ...q };
          delete content.status;
          const hash = createHash("sha256").update(JSON.stringify(content)).digest("hex");
          await tx`INSERT INTO java_question_bank (id, version, status, content_hash, question)
            VALUES (${q.id}, ${q.version}, 'draft', ${hash}, ${tx.json(q)}) ON CONFLICT (id, version) DO NOTHING`;
          const [stored] = await tx`SELECT content_hash FROM java_question_bank WHERE id = ${q.id} AND version = ${q.version}`;
          if (stored.content_hash !== hash) throw new Error(`Content changed without a version bump: ${q.id} v${q.version}`);
        }
      });
      console.log(`Loaded ${bank.length} immutable question revisions. Review drafts with 'list'; publish each reviewed ID/version explicitly.`);
    } else if (command === "list") {
      const rows = await sql`SELECT id, version, status, question FROM java_question_bank ORDER BY id, version`;
      console.log(JSON.stringify(rows, null, 2));
    } else if (command === "review") {
      const rows = await sql`SELECT question_id, question_version, count(*)::int AS ratings,
        round(avg(rating), 2) AS average_stars, count(*) FILTER (WHERE flag IS NOT NULL)::int AS flags,
        array_agg(DISTINCT flag) FILTER (WHERE flag IS NOT NULL) AS reasons,
        count(*) FILTER (WHERE flag IS NOT NULL AND review_status = 'pending')::int AS pending_flags
        FROM java_question_feedback WHERE expires_at > now() GROUP BY question_id, question_version ORDER BY pending_flags DESC, question_id`;
      console.log(JSON.stringify(rows, null, 2));
    } else {
      const version = Number(versionText);
      if (!argument || !Number.isInteger(version) || version < 1) throw new Error("An exact question ID and version are required");
      const rows = await sql`SELECT question FROM java_question_bank WHERE id = ${argument} AND version = ${version}`;
      if (!rows.length) throw new Error("Question revision not found");
      if (command === "publish") validateBank(rows.map((r) => r.question));
      if (command === "resolve") {
        await sql`UPDATE java_question_feedback SET review_status = 'resolved' WHERE question_id = ${argument} AND question_version = ${version}`;
      } else {
        const status = command === "publish" ? "published" : "retired";
        await sql`UPDATE java_question_bank SET status = ${status} WHERE id = ${argument} AND version = ${version}`;
      }
      console.log(`${command}: ${argument} v${version}`);
    }
  }
} catch (error) {
  // postgres error messages can contain connection details. Keep database failures bounded.
  console.error(error?.name === "PostgresError" ? `Database operation failed (${error.code})` : error.message);
  process.exitCode = 1;
} finally { if (sql) await sql.end(); }
