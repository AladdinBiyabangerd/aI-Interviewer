# Interview Prep web application

This directory contains the standard Next.js 16 application deployed by Vercel. It
supports English and Azerbaijani and implements the complete production text journey:

- company, role, job requirements, stage, and interview-language input;
- optional direct upload to a private persistent Vercel Blob store;
- durable asynchronous OpenAI company research and separate private CV review;
- evidence-linked likely questions and transparent coverage;
- persisted Real Interview and Practice sessions;
- answer-dependent adaptive follow-ups and feedback;
- a final report generated from the candidate's saved answers.

All application requests are same-origin. OpenAI, database, Blob, webhook, cron, and
session secrets are read only in Node.js Route Handlers. There is no browser fallback
that silently replaces failed production research with fabricated demo results.

## Local development

Node.js 22.13 or newer and a PostgreSQL database at migration head are required. Copy
`.env.example` to the ignored `.env.local`, use non-production credentials, then run:

```powershell
npm install
npm run dev
```

Vercel Blob upload-completion callbacks cannot call localhost. For end-to-end local CV
testing, use a secure tunnel and set `VERCEL_BLOB_CALLBACK_URL` to its public origin, or
test the deployed Preview environment. No-CV analysis works without that callback.

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
