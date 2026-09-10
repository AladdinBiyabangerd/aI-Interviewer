// Run against a running local Next.js server bound to a disposable migrated database.
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { spawnSync } from "node:child_process";
import postgres from "postgres";
import { questionBank } from "../lib/server/assessment-bank.ts";
import { defaultTopics } from "../lib/assessment.ts";

const base = new URL(process.env.ASSESSMENT_TEST_BASE_URL);
const db = new URL(process.env.DATABASE_URL);
if (!["localhost", "127.0.0.1"].includes(base.hostname) || !["localhost", "127.0.0.1"].includes(db.hostname)
  || !/^\/ai_interviewer_test_java_\d+$/.test(db.pathname)) throw new Error("Use a local disposable ai_interviewer_test_java_<timestamp> database and local test server");
const sql = postgres(process.env.DATABASE_URL, { max: 2 });
function client() {
  let cookie = "";
  return async (path, body, extraHeaders = {}) => {
    const response = await fetch(new URL(path, base), { method: body ? "POST" : "GET", headers: { ...(cookie ? { cookie } : {}), ...(body ? { "Content-Type": "application/json" } : {}), ...extraHeaders }, ...(body ? { body: JSON.stringify(body) } : {}) });
    cookie = response.headers.get("set-cookie")?.split(";")[0] ?? cookie;
    const data = await response.json();
    return { status: response.status, data };
  };
}
const owner = client();
const other = client();
const setup = () => ({ requestId: randomUUID(), level: "Junior", topicIds: defaultTopics.Junior, company: null });
function cli(...args) {
  const run = spawnSync(process.execPath, ["--experimental-strip-types", "scripts/question-bank.mjs", ...args], { cwd: process.cwd(), env: process.env, encoding: "utf8" });
  assert.equal(run.status, 0, run.stderr + run.stdout);
  return run.stdout;
}
try {
  assert.equal((await sql`SELECT id FROM java_question_bank LIMIT 1`).length, 0, "Use a fresh disposable test database");
  assert.equal((await owner("/api/health")).data.code, "question_bank_incomplete");
  cli("seed");
  cli("seed"); // exact immutable imports are idempotent
  assert.equal((await owner("/api/assessments", setup())).status, 503, "Draft questions must never be served");
  // Publish test fixtures only in the explicitly guarded disposable database.
  await sql`UPDATE java_question_bank SET status = 'published'`;
  assert.equal((await owner("/api/health")).status, 200);
  const input = setup();
  const started = await owner("/api/assessments", input);
  assert.equal(started.status, 201);
  let view = started.data.assessment;
  const id = view.id;
  assert.equal(view.question.correct, undefined);
  assert.equal(view.question.explanation, undefined);
  assert.equal(view.question.topic, "core-java");
  assert.equal((await owner("/api/assessments", input)).data.assessment.id, id);
  assert.equal((await owner("/api/assessments", { ...input, level: "Mid" })).status, 409);
  assert.equal((await other(`/api/assessments/${id}`)).status, 404);
  assert.equal((await other(`/api/assessments/${id}`, { action: "finish" })).status, 404);
  assert.equal((await owner(`/api/assessments/${id}`, { action: "feedback", questionId: view.question.id, rating: 5 })).status, 400);
  assert.equal((await owner(`/api/assessments/${id}`, { action: "answer", questionId: view.question.id, selected: ["missing"] })).status, 400);
  const first = questionBank.find((q) => q.id === view.question.id);
  const answer = { action: "answer", questionId: first.id, selected: first.correct };
  assert.equal((await owner(`/api/assessments/${id}`, answer, { origin: "https://attacker.example" })).status, 403);
  const retries = await Promise.all([owner(`/api/assessments/${id}`, answer), owner(`/api/assessments/${id}`, answer)]);
  assert.ok(retries.every((r) => r.status === 200 && r.data.assessment.answered === 1 && r.data.assessment.earned === 10));
  view = retries[0].data.assessment;
  assert.equal((await owner(`/api/assessments/${id}`, { ...answer, selected: ["b"] })).status, 409);
  assert.equal((await owner(`/api/assessments/${id}`)).data.assessment.question.id, view.question.id);
  const second = questionBank.find((q) => q.id === view.question.id);
  assert.equal(second.type, "multiple");
  view = (await owner(`/api/assessments/${id}`, { action: "answer", questionId: second.id, selected: [second.correct[0]] })).data.assessment;
  assert.equal(view.feedback.score, 5);
  assert.equal(view.question.topic, "collections");
  view = (await owner(`/api/assessments/${id}`, { action: "feedback", questionId: second.id, rating: 2, flag: "unclear" })).data.assessment;
  assert.equal(view.feedback.rating, 2);
  assert.equal(view.feedback.flag, "unclear");
  await owner(`/api/assessments/${id}`, { action: "feedback", questionId: second.id, rating: 4 });
  const [counts] = await sql`SELECT count(*)::int AS total, max(rating) AS rating FROM java_question_feedback WHERE question_id = ${second.id}`;
  assert.equal(counts.total, 1); assert.equal(counts.rating, 4);
  assert.match(cli("review"), /unclear/);
  cli("resolve", second.id, "1");
  const [resolved] = await sql`SELECT review_status FROM java_question_feedback WHERE question_id = ${second.id}`;
  assert.equal(resolved.review_status, "resolved");
  // A question retirement changes new sessions, while the current snapshot stays valid.
  const snapshotId = view.question.id;
  cli("retire", snapshotId, "1");
  assert.equal((await owner(`/api/assessments/${id}`)).data.assessment.question.id, snapshotId);
  const fresh = (await other("/api/assessments", { ...setup(), topicIds: ["collections"] })).data.assessment;
  assert.notEqual(fresh.question.id, snapshotId);
  cli("publish", snapshotId, "1");
  let guard = 20;
  while (view.question && guard-- > 0) {
    const q = questionBank.find((q) => q.id === view.question.id);
    const result = await owner(`/api/assessments/${id}`, { action: "answer", questionId: q.id, selected: q.correct });
    assert.equal(result.status, 200);
    view = result.data.assessment;
  }
  assert.equal(view.status, "completed");
  assert.equal(view.answered, 14); assert.equal(view.earned, 135); assert.equal(view.possible, 140);
  assert.equal(view.percent, 96);
  assert.equal(view.history[1].rating, 4);
  assert.deepEqual((await owner(`/api/assessments/${id}`)).data.assessment, view);
  const early = (await owner("/api/assessments", setup())).data.assessment;
  await owner(`/api/assessments/${early.id}`, { action: "answer", questionId: early.question.id, selected: first.correct });
  const finalEarly = (await owner(`/api/assessments/${early.id}`, { action: "finish" })).data.assessment;
  assert.equal(finalEarly.finishedEarly, true);
  assert.equal(finalEarly.results.filter((r) => r.status === "unassessed").length, 4);
  await sql`UPDATE java_assessment_sessions SET expires_at = now() - interval '1 second' WHERE id = ${early.id}`;
  assert.equal((await owner(`/api/assessments/${early.id}`)).status, 404);
  for (const path of ["/api/practice-sessions", `/api/practice-sessions/${id}/answers`, `/api/practice-sessions/${id}/complete`, "/api/interview-preparations/analyze", "/api/cv/upload", "/api/webhooks/openai"]) assert.equal((await owner(path, {})).status, 410);
  console.log("HTTP integration passed: draft gating, owner isolation, redaction, concurrency, retries, partial scores, persistence, moderation, immutable snapshots, early completion, expiry and legacy endpoint restrictions.");
} finally { await sql.end(); }
