# Intervia web application

**Current public MVP:** Intervia has a field-neutral home page at `/` with an
Azerbaijani interface and English switch. Java is the first available interview track
at `/java`; future fields can be added as separate tracks. The general Java Q&A
assessment has a reusable 45-question English seed,
level/topic selection, adaptive difficulty, deferred scoring, Back/Skip navigation,
cookie-based resume, learning references, ratings and editorial flags. A separate Java 8 book-practice mode
samples 15 questions from 1,075 licensed, text-complete source questions; users can
flag extraction or answer-key issues. See the
[setup and editorial guide](../docs/java-assessment-mvp.md). It requires PostgreSQL at
`20260910_0016`, a signed session secret and the retention cron secret. Seed imports
enter draft; publish the exact revisions after review. OpenAI and Blob are not needed
for assessments. The former interview page is retained in `legacy/page.tsx` and its
public endpoints return 410.

Operator-supplied question PDFs use the private
[source-ingestion workflow](../docs/java-question-source-ingestion.md). Deterministic
extraction preserves page provenance and answer pairing; it does not use a model or
publish staged source wording.

## Historical interview implementation (not public in the MVP)

This directory retains the former English and Azerbaijani interview implementation for
reference, including:

- company, role, job requirements, stage, and interview-language input;
- optional direct upload to a private persistent Vercel Blob store;
- durable asynchronous OpenAI company research and separate private CV review;
- evidence-linked likely questions and transparent coverage;
- persisted Real Interview and Practice sessions;
- answer-dependent adaptive follow-ups and feedback;
- a final report generated from the candidate's saved answers.

These flows are no longer routed as the public product. Their generation, upload,
webhook and practice endpoints return HTTP 410. Do not provision OpenAI or Blob for the
current assessment unless approved cleanup of historical artifacts still needs them.

## Local development

Node.js 22.13 or newer and a PostgreSQL database at migration head are required.

**Easiest:** from the **monorepo root** run one script (DB + API + this app):

```bash
./scripts/dev-up.sh
```

Or only this frontend (DB must already be up and migrated):

```bash
# copy once if missing
cp .env.example .env.local   # then set DATABASE_URL / secrets — see root README

npm install
npm run dev
```

Assessment development needs no Vercel Blob callback or model provider.

## Verification

```powershell
npm run lint
npm run typecheck
npm test
npm run build
npm audit
```

For Vercel services, migrations, environment variables, webhooks, retention, and
post-deployment checks, see [`../docs/deployment/vercel.md`](../docs/deployment/vercel.md).
