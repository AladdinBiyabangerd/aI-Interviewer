# Java Q&A assessment MVP

The public Next.js app now starts with a general Java knowledge assessment and offers
an optional Java 8 book-practice question set. Company, job description and CV are not
required. The former interview UI lives in
`frontend/legacy/page.tsx` outside the routing tree; its generation, upload, webhook
and open-ended practice endpoints return HTTP 410 through `frontend/proxy.ts` and
the server handler guard, including requests that do not match the proxy.
There are no model calls in assessment creation, scoring, feedback or reporting.

## Scope and question content

The [Ingress Academy roadmap](https://ingress.academy/career-paths/ai-native-java-muhendisi/)
was inspected on September 10, 2026. This MVP maps its foundation and Junior material
to Java/OOP, collections/exceptions, Spring/REST, SQL/JPA, testing, responsible AI,
Git/Linux and build tools. Mid adds API security, containers/CI, AI integration and
observability. Senior adds concurrency, distributed systems, performance,
Kubernetes/resilience and agent evaluation. This is a topic sample, not a claim to
assess every roadmap competency or certify employment seniority.

`frontend/lib/server/assessment-bank.ts` contains 45 original seed questions across
15 topics, with three difficulty steps per topic. Every question has a stable ID,
version, level, topic, tags, integer complexity from 0–10, choice type, answer key,
short conceptual explanation and official learning reference. The seed avoids code
recitation and specialized banking compliance. It contains no copied interview bank
and no claims that a company asked a question. The Intervia interface defaults to
Azerbaijani and offers English as a switch. General and book question text, options
and explanations remain in their original English; the UI states this for book practice.

The licensed OCA/OCP Java SE 8 practice book contributes 1,075 usable
questions to a separate book collection in `java_question_bank`. A book attempt samples
15 questions without adapting difficulty. Nineteen visually ambiguous extraction items
remain private in `java_question_import_candidates`; one additional diagram item was
retired after visual review. Book questions preserve the source
chapter and page attribution and are labeled as automatically extracted, since they
have not received line-by-line human editorial review.

The original 45-question seed is AI-authored content with structural and scoring checks. This
is **not evidence of independent human editorial approval**. Imports enter draft so
the team can review the actual questions, answer keys and references before making
them available. A source link means the listed learning reference supports the idea;
it does not mean the original question was copied from that page.

## Adaptive and grading rules

- General assessment is the default. Choose Junior, Mid or Senior and 1–6 eligible
  topics. Defaults select five topics, allowing at most 15 questions.
- Each topic starts at its lowest available general difficulty. A score of at least
  7/10 unlocks the next higher difficulty. A lower score ends the topic immediately.
  At most three questions are asked per topic. Junior complexity is capped at 4,
  Mid at 7 and Senior at 10; higher-level topics are rejected for lower-level sessions.
- Single choice earns 10 for the correct option and 0 otherwise. Multiple choice:
  `10 × max(0, correct_selected / correct_total − incorrect_selected / incorrect_total)`,
  rounded to one decimal place. Choosing every option earns 0; scores never go negative.
- An answer must contain unique, valid option IDs. The browser never sends a trusted
  score. A student may also skip a question. New sessions permit Back and Next;
  changing an earlier general answer recalculates the following adaptive path.
  Scores, answer keys, explanations and history stay hidden until explicit completion.
  The signed HttpOnly session cookie restores the latest attempt after refresh, while
  an unsent choice is retained in browser local storage.
- The final percentage is earned points divided by `10 × submitted answers`.
  Skipped or unvisited questions do not contribute fabricated zeroes. Early completion
  identifies unassessed topics. Results show the target scope, observed difficulty,
  strengths in the sample, weaker topics, answer history and relevant study links.
- Different adaptive attempts are not directly comparable for ranking. Leaderboards,
  calibrated level placement, gamification and open-ended responses remain future work.

Company names optionally select matching sourced question contexts, with a maximum
of 20% of delivered questions and no company question at the start of a topic.
Matching ignores case and outer whitespace. Without eligible evidence the UI explains
the fallback to general questions. The shipped seed has no company interview reports,
so this fallback is currently expected. To add real context, a reviewer must supply
the company, interview role and a traceable source in `companyContexts`; check the
rights to use that material and do not invent attribution. General questions do not
become bank/compliance questions merely because a bank name is selected.

## Local or deployment setup

Use the existing release migration workflow to apply `20260910_0016` to the intended
database. Revisions `0015` and `0016` are additive: they introduce question revisions,
anonymous owner sessions, ratings/flags and private source-ingestion staging. Python ORM
metadata and both readiness revision constants are updated. Do not run destructive
migration tests on an application database. See
[`java-question-source-ingestion.md`](java-question-source-ingestion.md) for PDF extraction,
staging and review controls.

The Java assessment needs `DATABASE_URL`, `INTERVIEW_SESSION_SECRET` (at least 32 bytes)
and `CRON_SECRET` for scheduled cleanup. It does not need OpenAI or Blob credentials.
Keep existing credentials only if cleanup of previously retained interview artifacts
still needs them. Set `NEXT_PUBLIC_APP_URL` for deployed metadata.

From `frontend`, after configuring `.env.local` for the intended environment:

```powershell
npm run bank -- validate
npm run bank -- seed
npm run bank -- list
# Review each question's wording, correct options, explanation, level and references.
# Publish exact reviewed revisions, for example:
npm run bank -- publish core-java-1 1
npm run bank -- publish core-java-2 1
npm run bank -- publish core-java-3 1
npm run dev
```

Publish at least a general entry question for every topic you plan to offer. Publish
all three steps to make the full adaptive ladder available. Requests with unavailable
topics fail explicitly; no fabricated or live-generated fallback is used. Drafts do
not displace a previously published revision. The latest non-draft revision controls
availability: retiring it removes that question from new sessions instead of silently
falling back to an older revision. Readiness checks require the current migration and
published entry questions for all default topics.

## Editorial review and feedback

```powershell
npm run bank -- review
npm run bank -- retire collections-2 1
npm run bank -- import reviewed-questions.json
npm run bank -- publish collections-2 2
npm run bank -- resolve collections-2 1
```

`review` reports average stars, flag counts/reasons and pending review counts without
exporting browser owner hashes. Students can give 1–5 stars and flag incorrect,
unclear, overly difficult or questionable-source questions. Feedback is accepted only
for answered questions and upserted once per browser owner and question revision.
Changing a flag reopens review. Resolving a flag is separate from retiring or replacing
a question. Content imports validate the choice schema and HTTPS references. They are
create-only per `(id, version)` and reject changed content without a version bump.
Publishing and retiring require direct operator database access; no public admin route
or client-shipped answer bank exists.

Sessions retain immutable snapshots of the published questions selected at creation,
including explanations and keys. Revision changes or retirements apply to new sessions;
existing attempts keep reproducible scores. Exact answer retries return saved state;
changed retries and stale questions return conflict. Session writes take a row lock,
and every read/write is bound to the existing signed HttpOnly browser cookie. Session
creation is rate limited to ten per browser owner per ten minutes. This anonymous
identity is suitable for practice, not a tamper-proof competition identity.

Sessions and owner feedback expire under `INTERVIEW_RETENTION_DAYS` (default seven
days). The existing retention job deletes both. Question content is editorial data and
is retained independently. Cookie loss means past anonymous results cannot be recovered.

## Verification

```powershell
cd frontend
npm run lint
npm run typecheck
npm test
npm run bank -- validate
npm run build
```

Assessment tests exercise difficulty progression, skip behavior, exact totals, partial
credit, invalid answers, retry conflicts, public key redaction, level boundaries,
retirement, empty-bank errors, early results and the company-context cap. The existing
legacy regression tests now read the preserved non-routed implementation. Database
and HTTP integration checks must use a disposable database; see the integration test
script and repository migration tests. With a local Next.js server configured for a
fresh migrated `ai_interviewer_test_java_<timestamp>` database, set the same
`DATABASE_URL` and `ASSESSMENT_TEST_BASE_URL` in a separate shell and run
`npm run test:assessment:http`. This script deliberately refuses non-local URLs and
non-test database names. It imports and publishes test fixtures, exercises real HTTP
requests, then checks persisted feedback and editorial operations. It is not a
production smoke test.

Implementation verification on September 14, 2026: all 27 frontend tests, ESLint,
TypeScript and the optimized Next.js build passed. The real PostgreSQL migration
roundtrip/model-parity test passed; all 10 release-migration tests passed after
updating the release-image revision pin. The local HTTP integration script passed,
including duplicate concurrent submissions and editorial feedback persistence.
Additional live HTTP smoke checks confirmed cookie restoration, Back/Skip navigation,
adaptive recalculation, answer redaction during an attempt and final reveal. These
checks removed only their exact diagnostic session rows. No live provider request or
deployment was made. Browser automation exposed no browser surface, so visual/responsive
browser QA remains unverified. Full unrelated Python product-suite coverage was not rerun.
