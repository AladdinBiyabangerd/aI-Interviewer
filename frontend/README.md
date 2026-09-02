# Interview AI demo

Interactive English MVP for presenting the candidate preparation journey:

- preparation setup with sample CV and job description;
- simulated AI profile and role-fit analysis;
- three-question interview flow;
- a one-click guided answer path for reliable live presentations;
- scorecard, strengths, gaps, and a seven-day action plan.

The current frontend deliberately uses synthetic demo data. It does not upload a
real CV, call OpenAI, or persist candidate data yet.

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
