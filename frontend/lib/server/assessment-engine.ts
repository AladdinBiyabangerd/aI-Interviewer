import { availableTopics, levels, topics, type AssessmentView, type Level, type PublicQuestion, type TopicResult } from "../assessment.ts";
import type { BankQuestion } from "./assessment-bank.ts";

export type StoredAnswer = { questionId: string; selected: string[] | null; score: number | null; rating: number | null; flag: string | null };
export type AssessmentState = {
  mode?: "roadmap" | "book";
  questionCount?: number;
  flowVersion?: 2;
  turnIds?: string[];
  cursor?: number;
  id: string; level: Level; company: string | null; topicIds: string[];
  questions: BankQuestion[]; answers: StoredAnswer[]; currentId: string | null;
  finishedEarly: boolean;
  priorQuestionExposure?: Record<string, number>;
};
export class AssessmentError extends Error {
  status: number;
  constructor(message: string, status = 400) { super(message); this.status = status; }
}
export function parseSetup(value: unknown): { mode: "roadmap" | "book"; level: Level; company: string | null; topicIds: string[]; questionCount: number } {
  if (!value || typeof value !== "object") throw new AssessmentError("invalid_setup");
  const v = value as Record<string, unknown>;
  if (v.mode === "book") {
    const questionCount = v.questionCount === undefined ? 15 : v.questionCount;
    if (!Number.isInteger(questionCount) || (questionCount as number) < 5 || (questionCount as number) > 50
      || (questionCount as number) % 5 !== 0) throw new AssessmentError("invalid_setup");
    return { mode: "book", level: "Senior", company: null, topicIds: ["core-java"], questionCount: questionCount as number };
  }
  if (v.mode !== undefined && v.mode !== "roadmap") throw new AssessmentError("invalid_setup");
  const topicIds = Array.isArray(v.topicIds) ? v.topicIds as string[] : [];
  const questionCount = v.questionCount === undefined ? topicIds.length * 3 : v.questionCount;
  if (!levels.includes(v.level as Level) || !Array.isArray(v.topicIds)
    || v.topicIds.length < 1 || v.topicIds.length > 6
    || v.topicIds.some((id) => typeof id !== "string" || !availableTopics(v.level as Level).some((t) => t.id === id))
    || new Set(v.topicIds).size !== v.topicIds.length
    || !Number.isInteger(questionCount) || (questionCount as number) % v.topicIds.length !== 0
    || (questionCount as number) < v.topicIds.length || (questionCount as number) > v.topicIds.length * 3
    || (v.company !== null && v.company !== undefined && (typeof v.company !== "string" || v.company.length > 100))) {
    throw new AssessmentError("invalid_setup");
  }
  return { mode: "roadmap", level: v.level as Level, company: typeof v.company === "string" ? v.company.trim() || null : null, topicIds, questionCount: questionCount as number };
}

function sameCompany(a: string, b: string) { return a.trim().toLowerCase() === b.trim().toLowerCase(); }
const caps: Record<Level, number> = { Junior: 4, Mid: 7, Senior: 10 };
function stableRank(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index++) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}
function questionLimit(state: AssessmentState): number {
  return state.questionCount ?? (state.mode === "book" ? state.questions.length : state.topicIds.length * 3);
}
function questionsPerTopic(state: AssessmentState): number {
  return Math.max(1, Math.floor(questionLimit(state) / state.topicIds.length));
}
function selectQuestion(state: AssessmentState, topicId: string, minimum = -1): BankQuestion | undefined {
  const asked = new Set(state.answers.map((a) => a.questionId));
  // Company-specific material is capped at one in five delivered questions. Every
  // topic opens with a general foundation question. No company evidence is invented.
  const contextualCount = state.answers.filter((a) => state.questions.find((q) => q.id === a.questionId)?.companyContexts.length).length;
  const allowCompany = minimum >= 0 && contextualCount < Math.floor((state.answers.length + 1) / 5);
  return state.questions.filter((q) => q.topic === topicId && q.complexity > minimum && !asked.has(q.id)
    && (!q.companyContexts.length || (allowCompany && state.company && q.companyContexts.some((c) => sameCompany(c.company, state.company!)))))
    .sort((a, b) => a.complexity - b.complexity
      || Number(Boolean(b.companyContexts.length)) - Number(Boolean(a.companyContexts.length))
      || (state.priorQuestionExposure?.[a.id] ?? 0) - (state.priorQuestionExposure?.[b.id] ?? 0)
      || stableRank(`${state.id}:${topicId}:${minimum}:${a.id}`) - stableRank(`${state.id}:${topicId}:${minimum}:${b.id}`)
      || a.id.localeCompare(b.id))[0];
}

export function startAssessment(id: string, setup: Omit<ReturnType<typeof parseSetup>, "mode" | "questionCount"> & { mode?: "roadmap" | "book"; questionCount?: number }, bank: BankQuestion[], priorQuestionExposure: Record<string, number> = {}): AssessmentState {
  const state: AssessmentState = {
    id, ...setup, mode: "roadmap", questions: bank.filter((q) => q.status === "published" && q.collection !== "book" && setup.topicIds.includes(q.topic)
      && levels.indexOf(q.level) <= levels.indexOf(setup.level) && q.complexity <= caps[setup.level]
      && (!q.companyContexts.length || (setup.company && q.companyContexts.some((c) => sameCompany(c.company, setup.company!))))),
    answers: [], currentId: null, finishedEarly: false, priorQuestionExposure,
  };
  for (const topic of setup.topicIds) {
    if (!selectQuestion(state, topic)) throw new AssessmentError("topic_unavailable", 503);
  }
  state.currentId = selectQuestion(state, setup.topicIds[0])!.id;
  return state;
}

export function startBookAssessment(id: string, bank: BankQuestion[], questionCount = 15): AssessmentState {
  if (bank.length !== questionCount || questionCount < 5 || questionCount > 50 || questionCount % 5 !== 0
    || bank.some((q) => q.collection !== "book" || q.status !== "published")) {
    throw new AssessmentError("book_unavailable", 503);
  }
  return {
    id, mode: "book", questionCount, level: "Senior", company: null, topicIds: ["core-java"],
    questions: bank, answers: [], currentId: bank[0].id, finishedEarly: false,
  };
}

export function withDeferredResults(state: AssessmentState): AssessmentState {
  if (state.flowVersion === 2 || !state.currentId) return state;
  const turnIds = [...state.answers.map((answer) => answer.questionId), state.currentId];
  return { ...state, flowVersion: 2, turnIds, cursor: turnIds.length - 1 };
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
  const exact = selected.length === question.correct.length && hits === question.correct.length;
  const score = exact ? 10 : question.type === "single" ? 0
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
  if (state.mode === "book") {
    next.currentId = state.questions[next.answers.length]?.id ?? null;
    return next;
  }
  const topicAnswers = next.answers.filter((a) => state.questions.find((q) => q.id === a.questionId)?.topic === question.topic);
  // The chosen depth allows one to three questions per topic; one unsuccessful answer ends that topic.
  const harder = graded.score >= 7 && topicAnswers.length < questionsPerTopic(next) ? selectQuestion(next, question.topic, question.complexity) : undefined;
  const nextTopic = state.topicIds[state.topicIds.indexOf(question.topic) + 1];
  next.currentId = harder?.id ?? (nextTopic ? selectQuestion(next, nextTopic)?.id : null) ?? null;
  return next;
}

export function goBack(state: AssessmentState): AssessmentState {
  if (state.flowVersion !== 2 || !state.currentId || !state.turnIds || !state.cursor) {
    throw new AssessmentError("cannot_go_back", 409);
  }
  return { ...state, cursor: state.cursor - 1, currentId: state.turnIds[state.cursor - 1] };
}

export function advanceQuestion(state: AssessmentState, questionId: unknown, selection: unknown): AssessmentState {
  if (state.flowVersion !== 2 || !state.currentId || !state.turnIds || state.cursor === undefined)
    throw new AssessmentError("stale_question", 409);
  const question = state.questions.find((q) => q.id === questionId);
  if (!question) throw new AssessmentError("question_not_found", 404);
  const graded = selection === null ? null : grade(question, selection);
  const selected = graded?.selected ?? null;
  const prior = state.answers.find((a) => a.questionId === questionId);
  if (state.currentId !== questionId) {
    if (prior && JSON.stringify(prior.selected) === JSON.stringify(selected)) return state;
    throw new AssessmentError(prior ? "answer_already_saved" : "stale_question", 409);
  }
  if (prior && JSON.stringify(prior.selected) === JSON.stringify(selected)) {
    const following = state.turnIds[state.cursor + 1];
    return following ? { ...state, cursor: state.cursor + 1, currentId: following } : state;
  }
  const answer: StoredAnswer = { questionId: question.id, selected, score: graded?.score ?? null, rating: null, flag: null };
  const turnIds = state.mode === "book" ? [...state.turnIds] : state.turnIds.slice(0, state.cursor + 1);
  const answers = state.mode === "book"
    ? [...state.answers.filter((a) => a.questionId !== questionId), answer]
    : [...state.answers.filter((a) => turnIds.slice(0, -1).includes(a.questionId)), answer];
  let following: string | undefined = turnIds[state.cursor + 1];
  if (!following && state.mode === "book") following = state.questions[state.cursor + 1]?.id;
  if (!following && state.mode !== "book") {
    const next = { ...state, answers, turnIds };
    const topicAnswers = answers.filter((a) => state.questions.find((q) => q.id === a.questionId)?.topic === question.topic);
    const harder = (graded?.score ?? 0) >= 7 && topicAnswers.length < questionsPerTopic(next)
      ? selectQuestion(next, question.topic, question.complexity) : undefined;
    const nextTopic = state.topicIds[state.topicIds.indexOf(question.topic) + 1];
    following = harder?.id ?? (nextTopic ? selectQuestion(next, nextTopic)?.id : undefined);
  }
  if (following) {
    if (!turnIds.includes(following)) turnIds.push(following);
    return { ...state, answers, turnIds, cursor: state.cursor + 1, currentId: following };
  }
  return { ...state, answers, turnIds, currentId: question.id };
}

export function publicQuestion(q: BankQuestion): PublicQuestion {
  return { id: q.id, version: q.version, topic: q.topic, tags: q.tags, complexity: q.complexity,
    type: q.type, prompt: q.prompt, options: q.options, source: q.source, companyContexts: q.companyContexts };
}

function secureView(state: AssessmentState, view: AssessmentView): AssessmentView {
  const currentAnswer = state.answers.find((answer) => answer.questionId === state.currentId);
  const navigation = {
    skipped: state.answers.filter((answer) => answer.selected === null).length,
    completedCount: state.answers.length,
    currentIndex: state.flowVersion === 2 ? (state.cursor ?? 0) + 1 : state.answers.length + 1,
    selected: currentAnswer?.selected ?? [],
    canGoBack: state.flowVersion === 2 && Boolean(state.currentId) && (state.cursor ?? 0) > 0,
    readyToFinish: state.flowVersion === 2 && Boolean(state.currentId) && Boolean(currentAnswer)
      && (state.cursor ?? 0) === (state.turnIds?.length ?? 1) - 1,
  };
  if (state.flowVersion === 2 && state.currentId) return {
    ...view, ...navigation, earned: 0, possible: 0, percent: null,
    feedback: null, history: [], results: [], summary: "",
    completedTopics: state.answers.length, totalTopics: view.maximumQuestions,
  };
  return { ...view, ...navigation };
}

export function assessmentView(state: AssessmentState): AssessmentView {
  const orderedAnswers = state.flowVersion === 2
    ? (state.turnIds ?? []).flatMap((id) => state.answers.filter((answer) => answer.questionId === id))
    : state.answers;
  const history = orderedAnswers.map((a) => {
    const q = state.questions.find((q) => q.id === a.questionId)!;
    return { question: publicQuestion(q), selected: a.selected ?? [], correct: q.correct, score: a.score,
      skipped: a.selected === null, explanation: q.explanation, references: q.references, rating: a.rating, flag: a.flag };
  });
  const results: TopicResult[] = state.topicIds.map((id) => {
    const answers = history.filter((a) => a.question.topic === id && !a.skipped);
    const earned = Math.round(answers.reduce((sum, a) => sum + (a.score ?? 0), 0) * 10) / 10;
    const possible = answers.length * 10;
    const passed = answers.filter((a) => (a.score ?? 0) >= 7).map((a) => a.question.complexity);
    const references = [...new Map(answers.filter((a) => (a.score ?? 0) < 10).flatMap((a) => a.references).map((r) => [r.url, r])).values()];
    return { id, title: state.mode === "book" ? "Java 8 book practice" : topics.find((t) => t.id === id)!.title, earned, possible, answered: answers.length,
      highestPassed: state.mode === "book" ? null : passed.length ? Math.max(...passed) : null,
      status: !possible ? "unassessed" : earned / possible >= .8 ? "strong" : earned / possible >= .5 ? "developing" : "revisit", references };
  });
  const answered = history.filter((a) => !a.skipped).length;
  const skipped = history.length - answered;
  const earned = Math.round(history.reduce((sum, a) => sum + (a.score ?? 0), 0) * 10) / 10;
  const possible = answered * 10;
  const percent = possible ? Math.round(earned / possible * 100) : null;
  const current = state.questions.find((q) => q.id === state.currentId);
  const covered = results.filter((r) => r.answered).length;
  if (state.mode === "book") return secureView(state, {
    id: state.id, mode: "book", level: state.level, company: null, companyNotice: null,
    status: current ? "active" : "completed", question: current ? publicQuestion(current) : null,
    answered, skipped, completedCount: history.length, currentIndex: (state.cursor ?? history.length) + 1,
    selected: [], canGoBack: false, readyToFinish: false, maximumQuestions: questionLimit(state),
    completedTopics: history.length, totalTopics: state.questions.length,
    earned, possible, percent, feedback: history.at(-1) ?? null, history, results,
    summary: `You answered ${answered} and skipped ${skipped} of ${questionLimit(state)} sampled questions from the Java 8 practice book. Review your answers and source pages below.`,
    finishedEarly: state.finishedEarly,
  });
  const levelFeedback = percent === null ? "No answers scored yet."
    : percent >= 80 ? `Strong performance on the sampled ${state.level} material.`
    : percent >= 50 ? `Your ${state.level} knowledge is developing; revisit the topics below.`
    : `Build the foundations of the sampled ${state.level} topics before attempting harder questions.`;
  const hasCompanyEvidence = state.company && state.questions.some((q) => q.companyContexts.some((c) => sameCompany(c.company, state.company!)));
  return secureView(state, {
    id: state.id, mode: "roadmap", level: state.level, company: state.company,
    companyNotice: !state.company ? null : hasCompanyEvidence
      ? "Relevant sourced company questions may appear, capped at 20%. The assessment remains general."
      : `No published interview evidence for ${state.company} in these topics. You will receive the general assessment.`,
    status: current ? "active" : "completed", question: current ? publicQuestion(current) : null,
    answered, skipped, completedCount: history.length, currentIndex: (state.cursor ?? history.length) + 1,
    selected: [], canGoBack: false, readyToFinish: false, maximumQuestions: questionLimit(state),
    completedTopics: current ? state.topicIds.indexOf(current.topic) : (state.finishedEarly ? covered : state.topicIds.length),
    totalTopics: state.topicIds.length, earned, possible, percent,
    feedback: history.at(-1) ?? null, history, results,
    summary: `${levelFeedback} ${covered} of ${state.topicIds.length} selected topics sampled. This is a knowledge snapshot, not a job-level certification.`,
    finishedEarly: state.finishedEarly,
  });
}
