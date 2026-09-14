import type { BankQuestion } from "./assessment-bank.ts";

export type BookCandidate = {
  chapter_number: number;
  chapter_title: string;
  question_number: number;
  page_start: number;
  prompt: string;
  options: { id: string; text: string }[];
  correct: string[];
  explanation: string;
};

export function bookQuestion(candidate: BookCandidate, referenceUrl: string): BankQuestion {
  const chapter = String(candidate.chapter_number).padStart(2, "0");
  const number = String(candidate.question_number).padStart(3, "0");
  const source = {
    title: `OCA/OCP Java SE 8 Practice Tests · ${candidate.chapter_title}, p. ${candidate.page_start}`,
    url: referenceUrl,
  };
  return {
    id: `book-java8-c${chapter}-q${number}`,
    version: 1,
    topic: "core-java",
    level: "Senior",
    collection: "book",
    tags: ["Java 8 book", `Chapter ${candidate.chapter_number}`, candidate.chapter_title],
    complexity: 0,
    type: candidate.correct.length === 1 ? "single" : "multiple",
    prompt: candidate.prompt,
    options: candidate.options,
    correct: candidate.correct,
    explanation: candidate.explanation,
    source,
    references: [source],
    companyContexts: [],
    status: "published",
  };
}
