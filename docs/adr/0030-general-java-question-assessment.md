# ADR 0030: General Java assessment as the public MVP

Status: accepted for implementation from the supplied product feedback, September 10, 2026.

The prior public flow requires a company/JD, generates questions per candidate and
evaluates open-ended interview answers with AI. Feedback identified excessive company
specialization, heavy Junior expectations, inconsistent questions and unclear scores.

Replace the public entry point with a Java-only single/multiple-choice assessment
based on the Ingress roadmap. Store versioned questions in PostgreSQL, publish them
through an editorial workflow, and calculate deterministic per-answer and overall
scores. Ask increasing difficulty within selected level boundaries and stop a topic
after an unsuccessful answer. Use company context only when selected and sourced,
with a 20% cap; general material remains the default.

Keep the old UI outside Next.js routes and block its public generation/practice APIs.
The existing Python platform and research foundations remain available for later
work; no previous production, privacy or model-quality gate is claimed complete by
this change. The assessment operates without CV ingestion or model processing.

Tradeoffs: the first bank is a small original seed that needs editorial calibration;
adaptive percentages describe an attempt rather than objective seniority. Questions
and UI are English for this MVP. Anonymous signed-cookie persistence supports practice
but not cross-device recovery or trustworthy public leaderboards. All future company
interview claims require real sources. Detailed behavior and operations are documented
in [the MVP guide](../java-assessment-mvp.md).
