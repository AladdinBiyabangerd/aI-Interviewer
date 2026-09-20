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

### Admin question editor

`/admin` lets an authorized operator add Java questions manually or generate them through
an AI chat. Both paths save complete questions to `java_question_bank` as private drafts.
The operator can edit the answer key, explanation, and HTTPS source, then publish the
draft. Published questions enter new general Java assessments for their topic and level;
active sessions retain their original question snapshot. Editing a published question
creates a new draft revision. Retiring a question removes it from future assessments.

Run `npm run admin:setup` in `frontend/` to generate a local admin account. It writes
the username and a random password to the ignored `.admin-credentials` file and the
password hash to the ignored `.env.local` file. Open `/admin/login` to sign in. The
admin session uses a signed, `HttpOnly` cookie and expires after 12 hours. For a hosted
deployment, configure `INTERVIEW_ADMIN_USERNAME` and `INTERVIEW_ADMIN_PASSWORD_HASH`
from `.env.local` as server-only environment variables. Rotating the password with
`npm run admin:setup -- --rotate` also invalidates existing admin sessions.
AI generation also requires server-side `OPENAI_API_KEY` and uses
`OPENAI_INTERVIEW_MODEL` (default `gpt-5.5`). It saves at most three questions per
request and 30 AI questions per hour. The AI does not verify the supplied source URL,
so an operator must review each draft before publishing. No new migration is required.

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
