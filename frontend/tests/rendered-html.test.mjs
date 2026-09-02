import assert from "node:assert/strict";
import test from "node:test";

async function requestFromBuild(request, bindings = {}) {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(request, { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) }, ...bindings }, { waitUntil() {}, passThroughOnException() {} });
}

async function render() {
  return requestFromBuild(new Request("http://localhost/", { headers: { accept: "text/html" } }));
}

test("server-renders the focused English interview preparation entry point", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  const html = await response.text();
  assert.match(html, /<html lang="en">/i);
  assert.match(html, /Interview Prep — Prepare for the questions that matter/i);
  assert.match(html, /Prepare for the interview/);
  assert.match(html, /Prepare for an Interview/);
  assert.match(html, /PASHA Bank/);
  assert.match(html, /RAG &amp; LLM Systems/);
  assert.match(html, /What you get from one preparation/);
  assert.match(html, /Questions tailored to the vacancy/);
  assert.match(html, /Built around the interview/);
  assert.match(html, /How did you evaluate your RAG retrieval/);
  assert.match(html, /og\.png/);
  assert.doesNotMatch(html, /AI-assisted demo|AI Magic|Start AI|analytics/i);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape|react-loading-skeleton/i);
});

test("keeps the complete interview journey and backend boundary in focused modules", async () => {
  const { readFile } = await import("node:fs/promises");
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const api = await readFile(new URL("../lib/interview-api.ts", import.meta.url), "utf8");
  const uiCopy = await readFile(new URL("../lib/ui-copy.ts", import.meta.url), "utf8");
  const productSource = `${page}\n${uiCopy}`;

  for (const requiredCopy of [
    "Job Description / Requirements",
    "Add your CV",
    "Company-specific data",
    "Likely Interview Questions",
    "Why this question?",
    "Real Interview",
    "Practice Interview",
    "Submit Answer",
    "Interview complete",
  ]) {
    assert.ok(productSource.includes(requiredCopy), `missing journey copy: ${requiredCopy}`);
  }
  assert.match(api, /NEXT_PUBLIC_INTERVIEW_API_BASE_URL/);
  assert.match(api, /interview-preparations\/analyze/);
  assert.match(api, /companyCoverage: "Limited"/);
  assert.doesNotMatch(page, /avatar|camera|video interview|chat bubble/i);
});

test("offers complete Azerbaijani and English interface choices", async () => {
  const { readFile } = await import("node:fs/promises");
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const uiCopy = await readFile(new URL("../lib/ui-copy.ts", import.meta.url), "utf8");
  const api = await readFile(new URL("../lib/interview-api.ts", import.meta.url), "utf8");

  assert.match(page, />AZ<\/button>/);
  assert.match(page, />EN<\/button>/);
  assert.match(page, /document\.documentElement\.lang = uiLanguage/);
  assert.match(uiCopy, /Sizi həqiqətən gözləyən müsahibəyə hazırlaşın/);
  assert.match(uiCopy, /Müsahibə dili/);
  assert.match(uiCopy, /Ehtimal olunan müsahibə sualları/);
  assert.match(api, /details\.language !== "Azerbaijani"/);
  assert.match(api, /RAG sistemini production mühitinə çıxarmazdan əvvəl/);
});

test("keeps professional desktop scale without changing the responsive flow", async () => {
  const { readFile } = await import("node:fs/promises");
  const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");

  assert.match(css, /--app-width:\s*1240px/);
  assert.match(css, /--form-width:\s*1160px/);
  assert.match(css, /--content-width:\s*1180px/);
  assert.match(css, /\.header-inner\s*{[^}]*min-height:\s*68px/s);
  assert.match(css, /\.language-switch\s*{/);
  assert.match(css, /\.home-hero\s*{[^}]*grid-template-columns:\s*minmax\(0, 1\.04fr\)/s);
  assert.match(css, /\.home-intro h1\s*{[^}]*48px/s);
  assert.match(css, /\.interview-form input, \.interview-form select\s*{[^}]*height:\s*50px/s);
  assert.match(css, /\.important-field textarea\s*{[^}]*min-height:\s*240px/s);
  assert.match(css, /\.upload-field\s*{[^}]*min-height:\s*144px/s);
  assert.match(css, /@media \(max-width:\s*760px\)/);
});

test("keeps OpenAI research server-side and fails closed when no key is configured", async () => {
  const { readFile } = await import("node:fs/promises");
  const route = await readFile(new URL("../app/api/interview-preparations/analyze/route.ts", import.meta.url), "utf8");
  const api = await readFile(new URL("../lib/interview-api.ts", import.meta.url), "utf8");

  assert.match(route, /process\.env\.OPENAI_API_KEY/);
  assert.match(route, /type:\s*"web_search"/);
  assert.match(route, /web_search_call\.action\.sources/);
  assert.match(route, /sourceUrls/);
  assert.match(route, /store:\s*false/);
  assert.doesNotMatch(api, /OPENAI_API_KEY/);

  const response = await requestFromBuild(new Request("http://localhost/api/interview-preparations/analyze", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      company: "PASHA Bank",
      role: "AI Engineer",
      jobDescription: "Build and evaluate production RAG systems with Python, APIs, deployment and monitoring.",
      jobUrl: "",
      seniority: "Mid-level",
      stage: "Technical Interview",
      language: "English",
      cvFileName: null,
    }),
  }));
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), { code: "research_unavailable" });
});

test("keeps company labels tied to sources returned by the research provider", async () => {
  const officialUrl = "https://pashabank.az/about/digital-banking";
  const engineeringUrl = "https://engineering.example.org/pasha-bank-platform";
  const unsupportedUrl = "https://unverified.example.net/claim";
  const rawQuestion = (question, sourceUrls = [], category = "Technical Questions") => ({
    category,
    question,
    reason: "This tests a concrete requirement and the candidate's engineering judgment.",
    approach: ["State the assumptions and constraints.", "Explain the design and trade-offs.", "Define validation and operational metrics."],
    followUp: "What would make you change that decision?",
    sourceUrls,
  });
  const providerDocument = {
    status: "completed",
    error: null,
    output: [
      {
        type: "web_search_call",
        action: {
          sources: [
            { title: "PASHA Bank digital banking", url: officialUrl },
            { title: "PASHA Bank engineering platform", url: engineeringUrl },
          ],
        },
      },
      {
        type: "message",
        content: [{
          type: "output_text",
          text: JSON.stringify({
            summary: "Evidence-grounded preparation for PASHA Bank's AI Engineer role.",
            companySignals: [
              { signal: "The bank is expanding customer-facing digital banking services.", sourceUrls: [officialUrl] },
              { signal: "Its platform work creates production reliability constraints for AI services.", sourceUrls: [engineeringUrl] },
              { signal: "This unsupported signal must be discarded.", sourceUrls: [unsupportedUrl] },
            ],
            focusAreas: [
              { label: "RAG evaluation", priority: "High" },
              { label: "Production reliability", priority: "High" },
            ],
            questions: [
              rawQuestion("PASHA Bank is expanding digital banking services. How would you evaluate a customer-facing RAG assistant before release?", [officialUrl]),
              rawQuestion("How would you design failure isolation for AI services supporting PASHA Bank's platform?", [engineeringUrl], "System Design"),
              rawQuestion("Which privacy controls would you add to a banking retrieval pipeline?", [officialUrl]),
              rawQuestion("How would you monitor retrieval and generation quality in production?"),
              rawQuestion("Explain a trade-off you made in a Python API service."),
              rawQuestion("How would you prioritize model quality against latency?", [unsupportedUrl]),
            ],
          }),
          annotations: [
            { type: "url_citation", title: "PASHA Bank digital banking", url: officialUrl },
            { type: "url_citation", title: "PASHA Bank engineering platform", url: engineeringUrl },
          ],
        }],
      },
    ],
  };
  const calls = [];
  const originalFetch = globalThis.fetch;
  const originalKey = process.env.OPENAI_API_KEY;
  const originalModel = process.env.OPENAI_INTERVIEW_MODEL;
  process.env.OPENAI_API_KEY = "server-only-test-key";
  process.env.OPENAI_INTERVIEW_MODEL = "test-model";
  globalThis.fetch = async (_input, init) => {
    calls.push(JSON.parse(init.body));
    return Response.json(providerDocument);
  };
  let response;
  try {
    response = await requestFromBuild(new Request("http://localhost/api/interview-preparations/analyze", {
      method: "POST",
      headers: { "content-type": "application/json", "cf-connecting-ip": "company-grounding-test" },
      body: JSON.stringify({
        company: "PASHA Bank",
        role: "AI Engineer",
        jobDescription: "Build and evaluate production RAG systems with Python, APIs, deployment, privacy and monitoring.",
        jobUrl: "",
        seniority: "Mid-level",
        stage: "Technical Interview",
        language: "English",
        cvFileName: null,
      }),
    }));
  } finally {
    globalThis.fetch = originalFetch;
    if (originalKey === undefined) delete process.env.OPENAI_API_KEY;
    else process.env.OPENAI_API_KEY = originalKey;
    if (originalModel === undefined) delete process.env.OPENAI_INTERVIEW_MODEL;
    else process.env.OPENAI_INTERVIEW_MODEL = originalModel;
  }

  assert.equal(response.status, 200);
  const result = await response.json();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].store, false);
  assert.deepEqual(calls[0].tools, [{ type: "web_search", search_context_size: "medium" }]);
  assert.equal(result.analysisMode, "live_research");
  assert.equal(result.companyCoverage, "Strong");
  assert.equal(result.researchSources.length, 2);
  assert.equal(result.companySignals.length, 2);
  assert.equal(result.questions.filter((question) => question.specificity === "Company evidence").length, 3);
  const unsupportedQuestion = result.questions.find((question) => question.question.includes("latency"));
  assert.equal(unsupportedQuestion.specificity, "Vacancy");
  assert.deepEqual(unsupportedQuestion.evidence, []);
});
