import assert from "node:assert/strict";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(new Request("http://localhost/", { headers: { accept: "text/html" } }), { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } }, { waitUntil() {}, passThroughOnException() {} });
}

test("server-renders the focused English interview preparation entry point", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  const html = await response.text();
  assert.match(html, /<html lang="en">/i);
  assert.match(html, /Interview Prep — Prepare for the questions that matter/i);
  assert.match(html, /Prepare for your interview/);
  assert.match(html, /Prepare for an Interview/);
  assert.match(html, /Add the interview details/);
  assert.match(html, /Review likely questions/);
  assert.match(html, /Practice when you are ready/);
  assert.match(html, /og\.png/);
  assert.doesNotMatch(html, /AI-assisted demo|AI Magic|Start AI|analytics/i);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape|react-loading-skeleton/i);
});

test("keeps the complete interview journey and backend boundary in focused modules", async () => {
  const { readFile } = await import("node:fs/promises");
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const api = await readFile(new URL("../lib/interview-api.ts", import.meta.url), "utf8");

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
    assert.ok(page.includes(requiredCopy), `missing journey copy: ${requiredCopy}`);
  }
  assert.match(api, /NEXT_PUBLIC_INTERVIEW_API_BASE_URL/);
  assert.match(api, /interview-preparations\/analyze/);
  assert.match(api, /companyCoverage: "Limited"/);
  assert.doesNotMatch(page, /avatar|camera|video interview|chat bubble/i);
});
