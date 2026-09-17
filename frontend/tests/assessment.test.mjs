import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { questionBank } from "../lib/server/assessment-bank.ts";
import { validateBank } from "../lib/server/assessment-bank-validation.ts";
import { advanceQuestion, answerQuestion, assessmentView, goBack, grade, parseSetup, startAssessment, startBookAssessment, withDeferredResults } from "../lib/server/assessment-engine.ts";
import { bookQuestion, hasConsistentBookAnswer } from "../lib/server/book-questions.ts";
import { defaultTopics, levels, topics } from "../lib/assessment.ts";

function start(level = "Junior", topicIds = defaultTopics[level], bank = questionBank, company = null) {
  return startAssessment("test-session", parseSetup({ level, topicIds, company }), bank);
}
function current(state) { return state.questions.find((q) => q.id === state.currentId); }
function correct(state) { return answerQuestion(state, state.currentId, current(state).correct); }

test("the versioned bank has valid answers, sources and a three-step ladder for every roadmap topic", () => {
  validateBank(questionBank);
  assert.equal(questionBank.length, 135);
  for (const topic of topics) {
    const questions = questionBank.filter((q) => q.topic === topic.id);
    assert.equal(questions.length, 9);
    assert.equal(new Set(questions.map((q) => q.complexity)).size, 3);
    for (const complexity of new Set(questions.map((q) => q.complexity))) {
      assert.equal(questions.filter((q) => q.complexity === complexity).length, 3);
    }
  }
  assert.throws(() => validateBank([{ ...questionBank[0], correct: ["missing"] }]));
  assert.throws(() => validateBank([{ ...questionBank[0], type: "open" }]));
  assert.throws(() => validateBank([{ ...questionBank[0], companyContexts: [{ company: "Bank", role: "Junior" }] }]));
});
test("three consecutive roadmap sessions rotate exact questions without breaking deterministic navigation", () => {
  const exposure = {};
  const delivered = [];
  for (let session = 1; session <= 3; session++) {
    const id = `rotation-session-${session}`;
    let state = startAssessment(id, parseSetup({ level: "Junior", topicIds: defaultTopics.Junior, company: null }), questionBank, exposure);
    assert.equal(startAssessment(id, parseSetup({ level: "Junior", topicIds: defaultTopics.Junior, company: null }), questionBank, exposure).currentId, state.currentId);
    const ids = [];
    while (state.currentId) {
      ids.push(state.currentId);
      state = answerQuestion(state, state.currentId, current(state).correct);
    }
    assert.equal(ids.length, 15);
    assert.equal(new Set(ids).size, 15);
    assert.equal(ids.filter((questionId) => delivered.flat().includes(questionId)).length, 0);
    delivered.push(ids);
    for (const questionId of ids) exposure[questionId] = (exposure[questionId] ?? 0) + 1;
  }
});
test("Junior scope cannot activate advanced topics, invalid levels or duplicate topics", () => {
  for (const input of [{ level: "Junior", topicIds: ["concurrency"] }, { level: "Lead", topicIds: ["spring"] },
    { level: "Junior", topicIds: ["spring", "spring"] }, { level: "Junior", topicIds: [] },
    { level: "Junior", topicIds: ["spring"], company: 42 },
    { level: "Junior", topicIds: defaultTopics.Junior, questionCount: 7 },
    { mode: "book", questionCount: 12 }, { mode: "book", questionCount: 55 }]) assert.throws(() => parseSetup(input));
  assert.ok(start().questions.every((q) => q.level === "Junior" && q.complexity <= 4));
});
test("users can choose roadmap depth and book test length", () => {
  for (const depth of [1, 2, 3]) {
    const setup = parseSetup({ level: "Junior", topicIds: defaultTopics.Junior, questionCount: defaultTopics.Junior.length * depth });
    let state = withDeferredResults(startAssessment(`depth-${depth}`, setup, questionBank));
    let guard = 20;
    while (!assessmentView(state).readyToFinish && guard-- > 0) state = advanceQuestion(state, state.currentId, current(state).correct);
    const view = assessmentView(state);
    assert.equal(view.maximumQuestions, 5 * depth);
    assert.equal(view.answered, 5 * depth);
    assert.equal(view.readyToFinish, true);
  }
  const bookBank = Array.from({ length: 10 }, (_, index) => ({ ...questionBank[0], id: `short-book-${index}`, collection: "book" }));
  const book = startBookAssessment("short-book", bookBank, 10);
  assert.equal(assessmentView(book).maximumQuestions, 10);
  assert.equal(parseSetup({ mode: "book", questionCount: 50 }).questionCount, 50);
});
test("unanswered keys and explanations are never exposed in the session response", () => {
  const view = assessmentView(start());
  assert.equal(view.feedback, null);
  assert.equal(view.history.length, 0);
  assert.equal(view.question.correct, undefined);
  assert.equal(view.question.explanation, undefined);
  assert.equal(view.question.references, undefined);
  assert.equal(view.questions, undefined);
  assert.equal(view.percent, null);
});
test("deferred assessment hides all grading until finish and supports skip, back, and edits", () => {
  let state = withDeferredResults(start("Junior", ["core-java", "spring"]));
  const firstId = state.currentId;
  state = advanceQuestion(state, firstId, null);
  assert.equal(advanceQuestion(state, firstId, null), state);
  let view = assessmentView(state);
  assert.equal(view.skipped, 1);
  assert.equal(view.answered, 0);
  assert.deepEqual(view.history, []);
  assert.deepEqual(view.results, []);
  assert.equal(view.feedback, null);
  assert.equal(view.percent, null);
  assert.equal(view.earned, 0);
  assert.equal(view.question.correct, undefined);
  assert.equal(state.currentId, start("Junior", ["spring"]).currentId);

  state = goBack(state);
  view = assessmentView(state);
  assert.equal(view.currentIndex, 1);
  assert.equal(view.canGoBack, false);
  assert.deepEqual(view.selected, []);
  state = advanceQuestion(state, firstId, current(state).correct);
  assert.equal(state.answers.length, 1);
  assert.equal(state.answers[0].score, 10);
  assert.equal(current(state).complexity, 2);
  assert.equal(assessmentView(state).history.length, 0);
  const secondId = state.currentId;
  state = advanceQuestion(state, secondId, null);
  assert.equal(assessmentView(state).skipped, 1);
  const completed = assessmentView({ ...state, currentId: null, finishedEarly: true });
  assert.equal(completed.status, "completed");
  assert.equal(completed.possible, 10);
  assert.equal(completed.earned, 10);
  assert.equal(completed.history.length, 2);
  assert.equal(completed.history[1].skipped, true);
  assert.deepEqual(completed.history[0].correct, current(withDeferredResults(start("Junior", ["core-java", "spring"]))).correct);
});

test("saved assessments from the earlier flow regain previous-question navigation", () => {
  let legacy = start("Junior", ["core-java", "spring"]);
  const firstId = legacy.currentId;
  const firstAnswer = current(legacy).correct;
  legacy = answerQuestion(legacy, firstId, firstAnswer);
  const upgraded = withDeferredResults(legacy);
  assert.deepEqual(upgraded.turnIds, [firstId, legacy.currentId]);
  assert.equal(upgraded.cursor, 1);
  assert.equal(assessmentView(upgraded).canGoBack, true);
  assert.deepEqual(assessmentView(upgraded).history, []);

  const previous = goBack(upgraded);
  assert.equal(previous.currentId, firstId);
  assert.deepEqual(assessmentView(previous).selected, firstAnswer);
  const wrong = current(previous).options.find((option) => !current(previous).correct.includes(option.id)).id;
  const revised = advanceQuestion(previous, firstId, [wrong]);
  assert.equal(current(revised).topic, "spring");
  assert.equal(revised.answers.length, 1);
  assert.equal(revised.answers[0].score, 0);
  assert.equal(withDeferredResults(upgraded), upgraded);
  const completedLegacy = { ...legacy, currentId: null };
  assert.equal(withDeferredResults(completedLegacy), completedLegacy);
});

test("book flow can revisit a saved answer without losing later turns", () => {
  const bank = Array.from({ length: 15 }, (_, index) => ({ ...questionBank[0], id: `book-${index}`, collection: "book" }));
  let state = withDeferredResults(startBookAssessment("book-session", bank));
  state = advanceQuestion(state, state.currentId, [bank[0].correct[0]]);
  state = advanceQuestion(state, state.currentId, null);
  state = goBack(state);
  state = goBack(state);
  assert.deepEqual(assessmentView(state).selected, [bank[0].correct[0]]);
  const wrong = bank[0].options.find((option) => !bank[0].correct.includes(option.id)).id;
  state = advanceQuestion(state, state.currentId, [wrong]);
  assert.equal(state.currentId, bank[1].id);
  state = advanceQuestion(state, state.currentId, null);
  assert.equal(state.currentId, bank[2].id);
  assert.equal(assessmentView(state).completedCount, 2);
  assert.equal(assessmentView(state).history.length, 0);
});
test("choice grading gives partial credit, penalizes wrong selections and rejects malformed answers", () => {
  const q = questionBank.find((q) => q.type === "multiple");
  const wrong = q.options.find((o) => !q.correct.includes(o.id)).id;
  assert.equal(grade(q, q.correct).score, 10);
  assert.equal(grade(q, [q.correct[0]]).score, 5);
  assert.equal(grade(q, [q.correct[0], wrong]).score, 0);
  assert.equal(grade(q, q.options.map((o) => o.id)).score, 0);
  for (const selection of [[], ["unknown"], [q.correct[0], q.correct[0]], "a", null]) assert.throws(() => grade(q, selection));
  assert.throws(() => grade(questionBank[0], ["a", "b"]));
});
test("an exact answer always earns ten points regardless of selection order", () => {
  for (const question of questionBank) {
    assert.equal(grade(question, [...question.correct].reverse()).score, 10, question.id);
  }
});
test("book questions with an explicit answer-key contradiction are excluded", () => {
  const question = { ...questionBank[0], collection: "book", correct: ["a"] };
  assert.equal(hasConsistentBookAnswer({ ...question, explanation: "Option A is correct." }), true);
  assert.equal(hasConsistentBookAnswer({ ...question, explanation: "Option A is incorrect." }), true);
  assert.equal(hasConsistentBookAnswer({ ...question, explanation: "Option B is the correct answer." }), false);
});
test("every topic starts simple, increases on success and ends after a miss", () => {
  let state = start("Junior", ["core-java", "spring"]);
  assert.equal(current(state).complexity, 0);
  state = correct(state);
  assert.equal(current(state).complexity, 2);
  const wrong = current(state).options.find((o) => !current(state).correct.includes(o.id)).id;
  state = answerQuestion(state, state.currentId, [wrong]);
  assert.equal(current(state).topic, "spring");
  assert.equal(current(state).complexity, 1);
  assert.equal(state.answers.length, 2);
  assert.equal(assessmentView(state).completedTopics, 1);
});
test("a failed foundation skips the topic, and identical retries do not change scores", () => {
  const initial = start();
  const selected = [current(initial).options.find((o) => !current(initial).correct.includes(o.id)).id];
  const state = answerQuestion(initial, initial.currentId, selected);
  assert.notEqual(current(state).topic, current(initial).topic);
  assert.equal(answerQuestion(state, initial.currentId, selected), state);
  assert.throws(() => answerQuestion(state, initial.currentId, current(initial).correct), /answer_already_saved/);
  assert.throws(() => answerQuestion(state, "spring-3", ["b"]), /stale_question/);
});
test("all level defaults finish within 15 questions with exact totals", () => {
  for (const level of levels) {
    let state = start(level);
    let limit = 20;
    while (state.currentId && limit-- > 0) state = correct(state);
    const view = assessmentView(state);
    assert.equal(view.status, "completed");
    assert.equal(view.answered, 15);
    assert.equal(view.earned, 150);
    assert.equal(view.possible, 150);
    assert.equal(view.percent, 100);
    assert.equal(view.completedTopics, 5);
    assert.ok(view.results.every((r) => r.status === "strong"));
  }
});
test("early reports explicitly separate unanswered topics and use only submitted answers", () => {
  const answered = correct(start());
  const view = assessmentView({ ...answered, currentId: null, finishedEarly: true });
  assert.equal(view.earned, 10);
  assert.equal(view.possible, 10);
  assert.equal(view.finishedEarly, true);
  assert.equal(view.results.filter((r) => r.status === "unassessed").length, 4);
  assert.match(view.summary, /1 of 5/);
});
test("company selection falls back transparently and never invents interview provenance", () => {
  const general = start();
  const contextual = start("Junior", defaultTopics.Junior, questionBank, "PASHA Bank");
  assert.equal(general.currentId, contextual.currentId);
  assert.match(assessmentView(contextual).companyNotice, /No published interview evidence/);
  assert.equal(assessmentView(general).companyNotice, null);
  assert.ok(questionBank.every((q) => q.companyContexts.length === 0));
});
test("verified company variants are capped at 20% at every step and cannot open a topic", () => {
  const variants = questionBank.filter((q) => q.level === "Junior").map((q) => ({ ...q, id: `${q.id}-company`, companyContexts: [{ company: "Test Company", role: "Junior", source: { title: "Test evidence", url: "https://example.com/evidence" } }] }));
  let state = start("Junior", defaultTopics.Junior, [...questionBank, ...variants], "Test Company");
  let count = 0;
  while (state.currentId) {
    const q = current(state);
    if (!state.answers.some((a) => state.questions.find((v) => v.id === a.questionId).topic === q.topic)) assert.equal(q.companyContexts.length, 0);
    if (q.companyContexts.length) count++;
    assert.ok(count <= Math.floor((state.answers.length + 1) / 5));
    state = correct(state);
  }
  assert.ok(count > 0);
});
test("retired questions are excluded, and unavailable topics fail honestly", () => {
  assert.throws(() => start("Junior", ["spring"], questionBank.map((q) => ({ ...q, status: "retired" }))), /topic_unavailable/);
});

test("book practice keeps licensed questions separate and advances through 15 sampled turns", () => {
  const candidate = {
    chapter_number: 1, chapter_title: "Java Basics", question_number: 1, page_start: 21,
    prompt: "Choose an entry point.\npublic static void main(String[] args)",
    options: [{ id: "A", text: "valid" }, { id: "B", text: "invalid" }, { id: "C", text: "other" }],
    correct: ["A"], explanation: "The method is public and static.",
  };
  const sample = Array.from({ length: 15 }, (_, index) => bookQuestion({ ...candidate, question_number: index + 1 }, "https://example.com/book"));
  validateBank(sample);
  assert.equal(parseSetup({ mode: "book" }).mode, "book");
  assert.throws(() => startBookAssessment("id", sample.slice(1)), /book_unavailable/);
  assert.equal(start("Junior", defaultTopics.Junior, [...questionBank, ...sample]).questions.some((question) => question.collection === "book"), false);
  let state = startBookAssessment("id", sample);
  for (let turn = 0; turn < 15; turn++) {
    const view = assessmentView(state);
    assert.equal(view.mode, "book");
    assert.equal(view.maximumQuestions, 15);
    assert.equal(view.answered, turn);
    assert.equal(view.question.correct, undefined);
    assert.equal(view.question.explanation, undefined);
    state = answerQuestion(state, state.currentId, [turn % 2 ? "A" : "B"]);
  }
  const report = assessmentView(state);
  assert.equal(report.status, "completed");
  assert.equal(report.answered, 15);
  assert.equal(report.completedTopics, 15);
  assert.equal(report.history.length, 15);
  assert.equal(report.history[0].question.source.title.includes("p. 21"), true);
});
test("public MVP exposes no old interview entry points or bank imports", async () => {
  const home = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const java = await readFile(new URL("../app/java/page.tsx", import.meta.url), "utf8");
  assert.match(home, /href="\/java"/);
  assert.match(home, /Yeni sahələr/);
  assert.match(java, /href="\/"/);
  assert.match(java, /\/api\/assessments/);
  for (const page of [home, java]) assert.doesNotMatch(page, /assessment-bank|interview-api|textarea|prepareInterview/);
  const proxy = await readFile(new URL("../proxy.ts", import.meta.url), "utf8");
  for (const path of ["practice-sessions", "interview-preparations", "cv", "webhooks/openai"]) assert.ok(proxy.includes(path));
  assert.match(proxy, /status: 410/);
  const routes = ["practice-sessions", "practice-sessions/[sessionId]/answers", "practice-sessions/[sessionId]/complete", "interview-preparations/analyze", "interview-preparations/analyze/[jobId]", "interview-preparations/recent", "cv/upload", "webhooks/openai"];
  for (const route of routes) {
    const source = await readFile(new URL(`../app/api/${route}/route.ts`, import.meta.url), "utf8");
    assert.match(source, /const blocked = publicInterviewGuard\(\);\s*if \(blocked\) return blocked;/);
  }
});
