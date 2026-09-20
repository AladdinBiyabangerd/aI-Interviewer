import assert from "node:assert/strict";
import test from "node:test";

import { bankQuestion, parseQuestionInput } from "../lib/admin-question.ts";
import { publicQuestion, startAssessment } from "../lib/server/assessment-engine.ts";
import { validateBank } from "../lib/server/assessment-bank-validation.ts";

const input = {
  topic: "core-java", level: "Junior", complexity: 1,
  prompt: "Which Java collection keeps unique elements?",
  options: ["Set", "List", "Queue", "Array"], correct: ["a"],
  explanation: "A Set rejects duplicate elements according to equality rules.",
  sourceTitle: "Oracle Collections", sourceUrl: "https://dev.java/learn/api/collections-framework/",
  tags: ["collections"],
};

test("admin question has the assessment bank shape and keeps answers private", () => {
  const question = bankQuestion(parseQuestionInput(input), "manual");
  validateBank([question]);
  assert.equal(question.status, "draft");
  assert.equal(question.editorialOrigin, "manual");
  assert.deepEqual(question.correct, ["a"]);
  assert.equal("correct" in publicQuestion(question), false);
  assert.equal("explanation" in publicQuestion(question), false);
});

test("only a published admin question can enter a new user assessment", () => {
  const draft = bankQuestion(parseQuestionInput(input), "ai");
  const setup = { level: "Junior", company: null, topicIds: ["core-java"], questionCount: 1 };
  assert.throws(() => startAssessment("session", setup, [draft]), /topic_unavailable/);
  const published = { ...draft, status: "published" };
  const state = startAssessment("session", setup, [published]);
  assert.equal(state.currentId, published.id);
  assert.equal(state.questions[0].editorialOrigin, "ai");
});

test("invalid answer keys and source URLs cannot become drafts", () => {
  assert.throws(() => parseQuestionInput({ ...input, correct: ["e"] }), /invalid_question/);
  assert.throws(() => parseQuestionInput({ ...input, sourceUrl: "http://example.com" }), /invalid_question/);
  assert.throws(() => parseQuestionInput({ ...input, options: ["same", "same", "third", "fourth"] }), /invalid_question/);
  assert.throws(() => parseQuestionInput({ ...input, complexity: 9 }), /invalid_question/);
  assert.throws(() => parseQuestionInput({ ...input, topic: "security" }), /invalid_question/);
});
