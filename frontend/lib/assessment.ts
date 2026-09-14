export const levels = ["Junior", "Mid", "Senior"] as const;
export type Level = typeof levels[number];
export const roadmapUrl = "https://ingress.academy/career-paths/ai-native-java-muhendisi/";
export const topics: { id: string; title: string; level: Level; summary: string }[] = [
  { id: "core-java", title: "Core Java & OOP", level: "Junior", summary: "Objects, types and everyday language concepts" },
  { id: "collections", title: "Collections & exceptions", level: "Junior", summary: "Choose data structures and handle failures" },
  { id: "spring", title: "Spring & REST", level: "Junior", summary: "Dependencies, HTTP and backend applications" },
  { id: "data", title: "SQL & persistence", level: "Junior", summary: "Queries, transactions and JPA" },
  { id: "testing", title: "Testing & responsible AI", level: "Junior", summary: "Verify behavior and review generated code" },
  { id: "tools", title: "Git, Linux & builds", level: "Junior", summary: "Everyday development tools" },
  { id: "security", title: "API security", level: "Mid", summary: "Identity, access control and safe APIs" },
  { id: "delivery", title: "Containers & CI/CD", level: "Mid", summary: "Build, test and deliver consistently" },
  { id: "ai", title: "LLMs, RAG & tools", level: "Mid", summary: "Connect AI features to Java services" },
  { id: "observability", title: "Observability", level: "Mid", summary: "Understand application health and failures" },
  { id: "concurrency", title: "Java concurrency", level: "Senior", summary: "Shared state, execution and tradeoffs" },
  { id: "distributed", title: "Distributed systems & Kafka", level: "Senior", summary: "Delivery, consistency and failure handling" },
  { id: "performance", title: "JVM, caching & performance", level: "Senior", summary: "Measure bottlenecks and manage resources" },
  { id: "operations", title: "Kubernetes & resilience", level: "Senior", summary: "Operate and recover distributed services" },
  { id: "agents", title: "AI agents & evaluation", level: "Senior", summary: "Evaluate reliability, latency and cost" },
];
export const defaultTopics: Record<Level, string[]> = {
  Junior: ["core-java", "collections", "spring", "data", "testing"],
  Mid: ["spring", "security", "delivery", "ai", "observability"],
  Senior: ["concurrency", "distributed", "performance", "operations", "agents"],
};
export function availableTopics(level: Level) {
  return topics.filter((topic) => levels.indexOf(topic.level) <= levels.indexOf(level));
}
export type Reference = { title: string; url: string };
export type CompanyContext = { company: string; role: string; source: Reference };
export type PublicQuestion = {
  id: string; version: number; topic: string; tags: string[]; complexity: number;
  type: "single" | "multiple"; prompt: string; options: { id: string; text: string }[];
  source: Reference; companyContexts: CompanyContext[];
};
export type AnswerFeedback = {
  question: PublicQuestion; selected: string[]; correct: string[]; score: number | null; skipped: boolean;
  explanation: string; references: Reference[];
  rating: number | null; flag: string | null;
};
export type TopicResult = {
  id: string; title: string; earned: number; possible: number; answered: number;
  highestPassed: number | null; status: "strong" | "developing" | "revisit" | "unassessed";
  references: Reference[];
};
export type AssessmentView = {
  id: string; mode: "roadmap" | "book"; level: Level; company: string | null; companyNotice: string | null;
  status: "active" | "completed"; question: PublicQuestion | null;
  answered: number; maximumQuestions: number; completedTopics: number; totalTopics: number;
  skipped: number; completedCount: number; currentIndex: number; selected: string[];
  canGoBack: boolean; readyToFinish: boolean;
  earned: number; possible: number; percent: number | null;
  feedback: AnswerFeedback | null; history: AnswerFeedback[]; results: TopicResult[];
  summary: string; finishedEarly: boolean;
};
