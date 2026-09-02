# Interview Prep frontend

Focused bilingual (English and Azerbaijani) MVP for preparing for a specific job interview:

- one clear form for company, role, vacancy requirements, stage, language and an optional CV;
- transparent analysis states and honest company-evidence coverage;
- grouped likely questions with source labels and concise relevance explanations;
- distinct Real Interview and Practice modes with follow-up questions;
- a focused final feedback summary without fake scores.

The frontend keeps its data contract in `lib/interview-api.ts`. By default it calls
the same-origin server route at `/api/interview-preparations/analyze`. That route uses
the OpenAI Responses API with web search to research public company evidence, returns
the sources it actually used, and labels a question as company-grounded only when its
evidence URL can be matched to those sources. It can also send an optional PDF or DOCX
CV to a separate, non-search request so private CV contents do not become web-search
queries.

If live research is unavailable, the browser falls back to a transparent deterministic
preview based on the vacancy and role. That preview is visibly labeled and does not
claim to have parsed the CV or discovered private, exact interview questions. An
external compatible analysis service can still be selected with
`NEXT_PUBLIC_INTERVIEW_API_BASE_URL`.

## Run locally

Node.js `>=22.13.0` is required.

```powershell
npm install
npm run dev
```

Open `http://localhost:3000`.

For live company research, add a private server-side key to `frontend/.env.local`:

```dotenv
OPENAI_API_KEY=replace-with-a-new-private-key
OPENAI_INTERVIEW_MODEL=gpt-5.5
```

Never prefix the key with `NEXT_PUBLIC_`; browser-visible variables are not secret.

## Verify

```powershell
npm test
npm run lint
npm exec tsc -- --noEmit
npm audit
```
