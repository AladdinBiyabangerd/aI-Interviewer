import { availableTopics, levels, topics, type AssessmentView, type Level, type PublicQuestion, type TopicResult } from "../assessment.ts";
import type { BankQuestion } from "./assessment-bank.ts";

export type StoredAnswer = { questionId: string; selected: string[]; score: number; rating: number | null; flag: string | null };
export type AssessmentState = {
  id: string; level: Level; company: string | null; topicIds: string[];
  questions: BankQuestion[]; answers: StoredAnswer[]; currentId: string | null;
  finishedEarly: boolean;
};
export class AssessmentError extends Error {
  status: number;
  constructor(message: string, status = 400) { super(message); this.status = status; }
}
export function parseSetup(value: unknown): { level: Level; company: string | null; topicIds: string[] } {
  if (!value || typeof value !== "object") throw new AssessmentError("invalid_setup");
  const v = value as Record<string, unknown>;
  if (!levels.includes(v.level as Level) || !Array.isArray(v.topicIds)
    || v.topicIds.length < 1 || v.topicIds.length > 6
    || v.topicIds.some((id) => typeof id !== "string" || !availableTopics(v.level as Level).some((t) => t.id === id))
    || new Set(v.topicIds).size !== v.topicIds.length
    || (v.company !== null && v.company !== undefined && (typeof v.company !== "string" || v.company.length > 100))) {
    throw new AssessmentError("invalid_setup");
  }
  return { level: v.level as Level, company: typeof v.company === "string" ? v.company.trim() || null : null, topicIds: v.topicIds as string[] };
}

function sameCompany(a: string, b: string) { return a.trim().toLowerCase() === b.trim().toLowerCase(); }
const caps: Record<Level, number> = { Junior: 4, Mid: 7, Senior: 10 };
function selectQuestion(state: AssessmentState, topicId: string, minimum = -1): BankQuestion | undefined {
  const asked = new Set(state.answers.map((a) => a.questionId));
  // Company-specific material is capped at one in five delivered questions. Every
  // topic opens with a general foundation question. No company evidence is invented.
  const contextualCount = state.answers.filter((a) => state.questions.find((q) => q.id === a.questionId)?.companyContexts.length).length;
  const allowCompany = minimum >= 0 && contextualCount < Math.floor((state.answers.length + 1) / 5);
  return state.questions.filter((q) => q.topic === topicId && q.complexity > minimum && !asked.has(q.id)
    && (!q.companyContexts.length || (allowCompany && state.company && q.companyContexts.some((c) => sameCompany(c.company, state.company!)))))
    .sort((a, b) => a.complexity - b.complexity || Number(Boolean(b.companyContexts.length)) - Number(Boolean(a.companyContexts.length)) || a.id.localeCompare(b.id))[0];
}

export function startAssessment(id: string, setup: ReturnType<typeof parseSetup>, bank: BankQuestion[]): AssessmentState {
  const state: AssessmentState = {
    id, ...setup, questions: bank.filter((q) => q.status === "published" && setup.topicIds.includes(q.topic)
      && levels.indexOf(q.level) <= levels.indexOf(setup.level) && q.complexity <= caps[setup.level]
      && (!q.companyContexts.length || (setup.company && q.companyContexts.some((c) => sameCompany(c.company, setup.company!))))),
    answers: [], currentId: null, finishedEarly: false,
  };
  for (const topic of setup.topicIds) {
    if (!selectQuestion(state, topic)) throw new AssessmentError("topic_unavailable", 503);
  }
  state.currentId = selectQuestion(state, setup.topicIds[0])!.id;
  return state;
}

export function grade(question: BankQuestion, selected: unknown): { selected: string[]; score: number } {
  if (!Array.isArray(selected) || selected.length < 1 || selected.length > question.options.length
    || selected.some((id) => typeof id !== "string" || !question.options.some((option) => option.id === id))
    || new Set(selected).size !== selected.length || (question.type === "single" && selected.length !== 1)) {
    throw new AssessmentError("invalid_options");
  }
  const hits = selected.filter((id) => question.correct.includes(id)).length;
  const wrong = selected.length - hits;
  const distractors = question.options.length - question.correct.length;
  const score = question.type === "single" ? (hits ? 10 : 0)
    : Math.round(Math.max(0, hits / question.correct.length - wrong / distractors) * 100) / 10;
  return { selected: [...selected].sort(), score };
}

export function answerQuestion(state: AssessmentState, questionId: unknown, selected: unknown): AssessmentState {
  const question = state.questions.find((q) => q.id === questionId);
  if (!question) throw new AssessmentError("question_not_found", 404);
  const graded = grade(question, selected);
  const prior = state.answers.find((a) => a.questionId === questionId);
  if (prior) {
    if (JSON.stringify(prior.selected) === JSON.stringify(graded.selected)) return state;
    throw new AssessmentError("answer_already_saved", 409);
  }
  if (!state.currentId || state.currentId !== questionId) throw new AssessmentError("stale_question", 409);
  const next: AssessmentState = { ...state, answers: [...state.answers, { questionId: question.id, ...graded, rating: null, flag: null }] };
  const topicAnswers = next.answers.filter((a) => state.questions.find((q) => q.id === a.questionId)?.topic === question.topic);
  // At most three questions per topic; one unsuccessful answer ends that topic.
  const harder = graded.score >= 7 && topicAnswers.length < 3 ? selectQuestion(next, question.topic, question.complexity) : undefined;
  const nextTopic = state.topicIds[state.topicIds.indexOf(question.topic) + 1];
  next.currentId = harder?.id ?? (nextTopic ? selectQuestion(next, nextTopic)?.id : null) ?? null;
  return next;
}

export function publicQuestion(q: BankQuestion): PublicQuestion {
  return { id: q.id, version: q.version, topic: q.topic, tags: q.tags, complexity: q.complexity,
    type: q.type, prompt: q.prompt, options: q.options, source: q.source, companyContexts: q.companyContexts };
}

export function assessmentView(state: AssessmentState): AssessmentView {
  const history = state.answers.map((a) => {
    const q = state.questions.find((q) => q.id === a.questionId)!;
    return { question: publicQuestion(q), selected: a.selected, correct: q.correct, score: a.score,
      explanation: q.explanation, references: q.references, rating: a.rating, flag: a.flag };
  });
  const results: TopicResult[] = state.topicIds.map((id) => {
    const answers = history.filter((a) => a.question.topic === id);
    const earned = Math.round(answers.reduce((sum, a) => sum + a.score, 0) * 10) / 10;
    const possible = answers.length * 10;
    const passed = answers.filter((a) => a.score >= 7).map((a) => a.question.complexity);
    const references = [...new Map(answers.filter((a) => a.score < 10).flatMap((a) => a.references).map((r) => [r.url, r])).values()];
    return { id, title: topics.find((t) => t.id === id)!.title, earned, possible, answered: answers.length,
      highestPassed: passed.length ? Math.max(...passed) : null,
      status: !possible ? "unassessed" : earned / possible >= .8 ? "strong" : earned / possible >= .5 ? "developing" : "revisit", references };
  });
  const earned = Math.round(history.reduce((sum, a) => sum + a.score, 0) * 10) / 10;
  const possible = history.length * 10;
  const percent = possible ? Math.round(earned / possible * 100) : null;
  const current = state.questions.find((q) => q.id === state.currentId);
  const covered = results.filter((r) => r.answered).length;
  const levelFeedback = percent === null ? "No answers scored yet."
    : percent >= 80 ? `Strong performance on the sampled ${state.level} material.`
    : percent >= 50 ? `Your ${state.level} knowledge is developing; revisit the topics below.`
    : `Build the foundations of the sampled ${state.level} topics before attempting harder questions.`;
  const hasCompanyEvidence = state.company && state.questions.some((q) => q.companyContexts.some((c) => sameCompany(c.company, state.company!)));
  return {
    id: state.id, level: state.level, company: state.company,
    companyNotice: !state.company ? null : hasCompanyEvidence
      ? "Relevant sourced company questions may appear, capped at 20%. The assessment remains general."
      : `No published interview evidence for ${state.company} in these topics. You will receive the general assessment.`,
    status: current ? "active" : "completed", question: current ? publicQuestion(current) : null,
    answered: history.length, maximumQuestions: state.topicIds.length * 3,
    completedTopics: current ? state.topicIds.indexOf(current.topic) : (state.finishedEarly ? covered : state.topicIds.length),
    totalTopics: state.topicIds.length, earned, possible, percent,
    feedback: history.at(-1) ?? null, history, results,
    summary: `${levelFeedback} ${covered} of ${state.topicIds.length} selected topics sampled. This is a knowledge snapshot, not a job-level certification.`,
    finishedEarly: state.finishedEarly,
  };
}
