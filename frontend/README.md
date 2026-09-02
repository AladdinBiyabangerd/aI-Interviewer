# Interview Prep frontend

Focused English MVP for preparing for a specific job interview:

- one clear form for company, role, vacancy requirements, stage, language and an optional CV;
- transparent analysis states and honest company-evidence coverage;
- grouped likely questions with source labels and concise relevance explanations;
- distinct Real Interview and Practice modes with follow-up questions;
- a focused final feedback summary without fake scores.

The frontend keeps its data contract in `lib/interview-api.ts`. When
`NEXT_PUBLIC_INTERVIEW_API_BASE_URL` is configured it calls the interview-analysis
endpoint. Without that value it uses a transparent, deterministic local preview
adapter so the complete journey remains demonstrable while the final backend
endpoint is being connected. The local adapter does not claim to have parsed an
uploaded CV or found private company interview questions.

## Run locally

Node.js `>=22.13.0` is required.

```powershell
npm install
npm run dev
```

Open `http://localhost:3000`.

## Verify

```powershell
npm test
npm run lint
npm exec tsc -- --noEmit
npm audit
```
