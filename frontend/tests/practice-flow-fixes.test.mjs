import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");

test("a canned static follow-up is never presented as an adaptive one", async () => {
  const answers = await readFile(path.join(root, "app", "api", "practice-sessions", "[sessionId]", "answers", "route.ts"), "utf8");
  assert.doesNotMatch(answers, /feedback\.adaptiveFollowUp\s*=\s*question\.followUp/);
  assert.match(answers, /hasFollowUp/);
  // A "question" turn with no real adaptive follow-up must advance like a
  // completed follow-up turn (skip straight ahead) rather than getting stuck
  // waiting on an empty pending_follow_up.
  const branch = answers.slice(answers.indexOf("if (hasFollowUp)"), answers.indexOf("return { followUp: null"));
  assert.match(branch, /awaiting_follow_up = true/);
});

test("the model is nudged and retried once before a follow-up is accepted as empty", async () => {
  const ai = await readFile(path.join(root, "lib", "server", "interview-ai.ts"), "utf8");
  const fn = ai.slice(ai.indexOf("async function requestPracticeFeedback"));
  assert.match(fn, /insistOnFollowUp:\s*false/);
  assert.match(fn, /insistOnFollowUp:\s*true/);
  assert.match(fn, /adaptiveFollowUp must never be an empty string/);
});

test("report generation locks the session row before calling the model", async () => {
  const complete = await readFile(path.join(root, "app", "api", "practice-sessions", "[sessionId]", "complete", "route.ts"), "utf8");
  const lockIndex = complete.indexOf("FOR UPDATE");
  const generateIndex = complete.indexOf("createPracticeReport(");
  const checkIndex = complete.indexOf("row.report");
  assert.ok(lockIndex > -1 && generateIndex > -1 && checkIndex > -1, "expected lock, report-null check and generation to all be present");
  assert.ok(lockIndex < checkIndex, "the report-null check must happen while the row is locked");
  assert.ok(checkIndex < generateIndex, "the row must be checked before an expensive report is generated");
});

test("practice progress reflects answered turns, including follow-ups, not just the primary question index", async () => {
  const page = await readFile(path.join(root, "app", "page.tsx"), "utf8");
  const component = page.slice(page.indexOf("function PracticeActive"), page.indexOf("function Report("));
  assert.match(component, /answeredTurns/);
  assert.match(component, /expectedTurns/);
  assert.doesNotMatch(component, /questionProgress\(index \+ 1, questions\.length\)/);
  assert.doesNotMatch(component, /"likely-follow-up"/);
});

test("a new practice session always remounts practice state instead of reusing a stale one", async () => {
  const page = await readFile(path.join(root, "app", "page.tsx"), "utf8");
  assert.match(page, /<PracticeActive key=\{practiceSessionId\}/);
});

test("the selected practice duration drives a real, visible countdown", async () => {
  const page = await readFile(path.join(root, "app", "page.tsx"), "utf8");
  assert.match(page, /durationMinutes/);
  assert.match(page, /setPracticeDurationMinutes\(Number\.parseInt\(duration, 10\)\)/);
  assert.match(page, /timeRemaining|timeUp/);
});

test("the loading screen reflects real elapsed time and backend research phase instead of freezing after a fixed timer", async () => {
  const api = await readFile(path.join(root, "lib", "interview-api.ts"), "utf8");
  assert.match(api, /phase:\s*AnalysisPhase \| null/);
  assert.match(api, /slow:\s*elapsedMs > SLOW_AFTER_MS/);

  const jobs = await readFile(path.join(root, "lib", "server", "analysis-jobs.ts"), "utf8");
  assert.match(jobs, /reviewing_cv/);

  const page = await readFile(path.join(root, "app", "page.tsx"), "utf8");
  assert.match(page, /waitingLines/);
  assert.match(page, /t\.analysis\.elapsed/);
});
