import assert from "node:assert/strict";
import test from "node:test";

import { hashAdminPassword, issueAdminSession, verifyAdminPassword, verifyAdminSession } from "../lib/server/admin-auth-core.ts";

test("admin password storage uses a salted hash", async () => {
  const password = "a-long-private-password-for-testing-123";
  const first = await hashAdminPassword(password);
  const second = await hashAdminPassword(password);
  assert.notEqual(first, second);
  assert.equal(first.includes(password), false);
  assert.equal(await verifyAdminPassword(password, first), true);
  assert.equal(await verifyAdminPassword("wrong-password", first), false);
  assert.equal(await verifyAdminPassword(password, "malformed"), false);
});

test("admin session requires a valid signature, current password hash and unexpired lifetime", async () => {
  const hash = await hashAdminPassword("a-long-private-password-for-testing-123");
  const secret = "a-secret-of-at-least-thirty-two-bytes";
  const now = 1_700_000_000_000;
  const token = issueAdminSession(secret, hash, "admin", now);
  const tampered = `${token.slice(0, -1)}${token.endsWith("A") ? "B" : "A"}`;
  assert.equal(verifyAdminSession(token, secret, hash, "admin", now), true);
  assert.equal(verifyAdminSession(tampered, secret, hash, "admin", now), false);
  assert.equal(verifyAdminSession(token, secret, hash, "other", now), false);
  assert.equal(verifyAdminSession(token, secret, `${hash}changed`, "admin", now), false);
  assert.equal(verifyAdminSession(token, secret, hash, "admin", now + 12 * 60 * 60 * 1000), false);
});
