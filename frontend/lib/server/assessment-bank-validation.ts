import { levels, topics } from "../assessment.ts";
import type { BankQuestion } from "./assessment-bank.ts";

export function validateBank(bank: unknown): asserts bank is BankQuestion[] {
  if (!Array.isArray(bank) || !bank.length) throw new Error("Question bank must be a non-empty array");
  const ids = new Set<string>();
  function reference(value: unknown) {
    if (!value || typeof value !== "object") return false;
    const r = value as Record<string, unknown>;
    try { return typeof r.title === "string" && r.title.length > 0 && typeof r.url === "string" && new URL(r.url).protocol === "https:"; }
    catch { return false; }
  }
  for (const q of bank) {
    if (!q || typeof q !== "object" || typeof q.id !== "string" || !/^[a-z0-9-]{1,100}$/.test(q.id)
      || ids.has(q.id) || !Number.isInteger(q.version) || q.version < 1
      || !levels.includes(q.level) || !topics.some((t) => t.id === q.topic)
      || !Number.isInteger(q.complexity) || q.complexity < 0 || q.complexity > 10
      || !["single", "multiple"].includes(q.type) || !["draft", "published", "retired"].includes(q.status)
      || typeof q.prompt !== "string" || !q.prompt.trim() || typeof q.explanation !== "string" || !q.explanation.trim()
      || !Array.isArray(q.tags) || !q.tags.length || q.tags.some((t: unknown) => typeof t !== "string")
      || !Array.isArray(q.options) || q.options.length < 3 || q.options.length > 6
      || q.options.some((o: { id?: unknown; text?: unknown }) => !o || typeof o.id !== "string" || typeof o.text !== "string" || !o.text.trim())
      || new Set(q.options.map((o: { id: string }) => o.id)).size !== q.options.length
      || !Array.isArray(q.correct) || !q.correct.length || q.correct.length >= q.options.length
      || new Set(q.correct).size !== q.correct.length || q.correct.some((id: unknown) => !q.options.some((o: { id: string }) => o.id === id))
      || (q.type === "single" ? q.correct.length !== 1 : q.correct.length < 2)
      || !reference(q.source) || !Array.isArray(q.references) || !q.references.length || !q.references.every(reference)
      || !Array.isArray(q.companyContexts) || q.companyContexts.some((c: { company?: unknown; role?: unknown; source?: unknown }) => !c || typeof c.company !== "string" || !c.company.trim() || typeof c.role !== "string" || !c.role.trim() || !reference(c.source))) {
      throw new Error(`Invalid question: ${q?.id ?? "unknown"}`);
    }
    ids.add(q.id);
  }
}
