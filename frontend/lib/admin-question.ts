import { randomUUID } from "node:crypto";
import { levels, topics, type Level } from "./assessment.ts";
import type { BankQuestion } from "./server/assessment-bank.ts";

export type QuestionInput = {
  topic: string;
  level: Level;
  complexity: number;
  prompt: string;
  options: string[];
  correct: string[];
  explanation: string;
  sourceTitle: string;
  sourceUrl: string;
  tags: string[];
};

export class AdminQuestionError extends Error {
  readonly code: string;
  readonly status: number;
  constructor(code: string, status = 400) { super(code); this.code = code; this.status = status; }
}

function text(value: unknown, max: number): string | null {
  if (typeof value !== "string") return null;
  const result = value.trim();
  return result && result.length <= max ? result : null;
}

function referenceUrl(value: unknown): string | null {
  const raw = text(value, 2048);
  if (!raw) return null;
  try {
    const url = new URL(raw);
    return url.protocol === "https:" && !url.username && !url.password ? url.toString() : null;
  } catch { return null; }
}

export function parseQuestionInput(value: unknown): QuestionInput {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new AdminQuestionError("invalid_question");
  const raw = value as Record<string, unknown>;
  const topic = text(raw.topic, 60);
  const level = raw.level;
  const prompt = text(raw.prompt, 2000);
  const explanation = text(raw.explanation, 3000);
  const sourceTitle = text(raw.sourceTitle, 300);
  const sourceUrl = referenceUrl(raw.sourceUrl);
  const options = Array.isArray(raw.options) ? raw.options.map((option) => text(option, 1000)) : [];
  const correct = raw.correct;
  const tags = Array.isArray(raw.tags) ? raw.tags.map((tag) => text(tag, 40)) : [];
  const topicDefinition = topics.find((item) => item.id === topic);
  const levelIndex = levels.indexOf(level as Level);
  const complexityCap = level === "Junior" ? 4 : level === "Mid" ? 7 : 10;
  if (!topicDefinition || levelIndex < levels.indexOf(topicDefinition.level)
    || !Number.isInteger(raw.complexity) || (raw.complexity as number) < 0 || (raw.complexity as number) > complexityCap
    || !prompt || !explanation || !sourceTitle || !sourceUrl
    || options.length !== 4 || options.some((option) => !option)
    || new Set(options.map((option) => option!.toLowerCase())).size !== options.length
    || !Array.isArray(correct) || correct.length < 1 || correct.length > 3
    || correct.some((id) => typeof id !== "string" || !["a", "b", "c", "d"].includes(id))
    || new Set(correct).size !== correct.length
    || tags.length > 5 || tags.some((tag) => !tag) || new Set(tags).size !== tags.length) {
    throw new AdminQuestionError("invalid_question");
  }
  return {
    topic: topicDefinition.id, level: level as Level, complexity: raw.complexity as number,
    prompt, options: options as string[], correct: correct as string[], explanation,
    sourceTitle, sourceUrl, tags: tags as string[],
  };
}

export function bankQuestion(input: QuestionInput, origin: "manual" | "ai", id = `admin-${randomUUID()}`, version = 1): BankQuestion {
  const reference = { title: input.sourceTitle, url: input.sourceUrl };
  return {
    id, version, topic: input.topic, level: input.level, complexity: input.complexity,
    tags: [input.topic, ...input.tags.filter((tag) => tag !== input.topic)],
    type: input.correct.length === 1 ? "single" : "multiple",
    prompt: input.prompt, options: input.options.map((option, index) => ({ id: "abcd"[index], text: option })),
    correct: input.correct, explanation: input.explanation,
    source: reference, references: [reference], companyContexts: [],
    status: "draft", editorialOrigin: origin,
  };
}

export function editableQuestion(question: BankQuestion): QuestionInput {
  return {
    topic: question.topic, level: question.level, complexity: question.complexity,
    prompt: question.prompt, options: question.options.map((option) => option.text),
    correct: question.correct, explanation: question.explanation,
    sourceTitle: question.source.title, sourceUrl: question.source.url,
    tags: question.tags.filter((tag) => tag !== question.topic),
  };
}
