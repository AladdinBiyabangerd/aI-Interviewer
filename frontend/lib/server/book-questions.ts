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

function optionIds(value: string): string[] {
  return [...value.matchAll(/\b[A-H]\b/gi)].map((match) => match[0].toUpperCase());
}

/**
 * Imported book material is only eligible when a definitive answer statement
 * does not contradict the stored key. Descriptions such as "Option A is
 * incorrect" are deliberately ignored because the prompt may ask for the
 * incorrect statement.
 */
export function hasConsistentBookAnswer(question: BankQuestion): boolean {
  const correct = new Set(question.correct.map((id) => id.toUpperCase()));
  const statements = question.explanation.split(/(?<=[.!?])\s+|\n+/);
  for (const statement of statements) {
    const mentions = [...statement.matchAll(/\bOptions?\s+([A-H](?:\s*(?:,|and|&)\s*[A-H])*)/gi)];
    for (let index = 0; index < mentions.length; index++) {
      const mentioned = mentions[index];
      const ids = optionIds(mentioned[1]);
      const start = (mentioned.index ?? 0) + mentioned[0].length;
      const end = mentions[index + 1]?.index ?? statement.length;
      const context = statement.slice(start, end).toLowerCase();
      const saysCorrect = /^\s*(?:is|are|was|were)\s+(?:the\s+)?(?:only\s+)?correct\s+answers?\b/.test(context)
        || /^\s*(?:is|are|was|were)\s+correct\s*(?:[.,;:]|$)/.test(context)
        || /^\s*(?:is|are|was|were)\s+(?:the\s+)?answers?\b/.test(context)
        || /^\s*(?:becomes?|making|makes)\b.{0,35}\bcorrect\s+answers?\b/.test(context);
      if (saysCorrect && ids.some((id) => !correct.has(id))) return false;
    }
  }
  return true;
}

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
