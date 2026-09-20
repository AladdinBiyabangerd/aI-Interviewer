import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map(async (entry) => {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(target);
    return /\.(?:ts|tsx)$/.test(entry.name) ? [target] : [];
  }));
  return nested.flat();
}

test("the deploy target is standard Next.js rather than the former edge preview build", async () => {
  const packageDocument = JSON.parse(await readFile(path.join(root, "package.json"), "utf8"));
  assert.equal(packageDocument.scripts.build, "next build");
  assert.equal(packageDocument.scripts.start, "next start");
  assert.equal(packageDocument.devDependencies?.vinext, undefined);
  assert.equal(packageDocument.devDependencies?.wrangler, undefined);
  const nextConfig = await readFile(path.join(root, "next.config.ts"), "utf8");
  assert.match(nextConfig, /output:\s*process\.env\.VERCEL\s*\?\s*undefined\s*:\s*["']standalone["']/);
  await readFile(path.join(root, "Dockerfile"), "utf8");
  await readFile(path.join(root, "railway.toml"), "utf8");
  await readFile(path.join(root, "vercel.json"), "utf8");
});

test("application sources contain no hardcoded localhost API target", async () => {
  const files = await sourceFiles(path.join(root, "app"));
  files.push(...await sourceFiles(path.join(root, "lib")));
  for (const file of files) {
    const source = await readFile(file, "utf8");
    assert.doesNotMatch(source, /https?:\/\/(?:localhost|127\.0\.0\.1)/i, file);
  }
});

test("all sensitive production configuration is server-only", async () => {
  const env = await readFile(path.join(root, ".env.example"), "utf8");
  for (const name of [
    "DATABASE_URL",
    "DATABASE_URL_UNPOOLED",
    "BLOB_READ_WRITE_TOKEN",
    "OPENAI_API_KEY",
    "INTERVIEW_SESSION_SECRET",
    "INTERVIEW_ADMIN_USERNAME",
    "INTERVIEW_ADMIN_PASSWORD_HASH",
    "OPENAI_WEBHOOK_SECRET",
    "CRON_SECRET",
  ]) {
    assert.match(env, new RegExp(`^${name}=`, "m"));
    assert.doesNotMatch(env, new RegExp(`NEXT_PUBLIC_${name}`));
  }
});

test("long research is backgrounded and every downstream phase is persisted", async () => {
  const ai = await readFile(path.join(root, "lib", "server", "interview-ai.ts"), "utf8");
  const migration = await readFile(
    path.resolve(root, "..", "migrations", "versions", "20260902_0014_vercel_interview_runtime.py"),
    "utf8",
  );
  assert.match(ai, /background:\s*true/);
  assert.match(ai, /store:\s*false/);
  assert.match(ai, /web_search/);
  for (const table of [
    "interview_cv_uploads",
    "interview_preparations",
    "interview_practice_sessions",
    "interview_practice_turns",
  ]) assert.match(migration, new RegExp(`\"${table}\"`));
});

test("CV and public web research are isolated provider requests", async () => {
  const ai = await readFile(path.join(root, "lib", "server", "interview-ai.ts"), "utf8");
  const research = ai.slice(ai.indexOf("export async function startResearch"), ai.indexOf("export async function startCvReview"));
  const cv = ai.slice(ai.indexOf("export async function startCvReview"), ai.indexOf("function collectSources"));
  assert.match(research, /web_search/);
  assert.doesNotMatch(research, /input_file/);
  assert.match(cv, /input_file/);
  assert.doesNotMatch(cv, /web_search/);
});
