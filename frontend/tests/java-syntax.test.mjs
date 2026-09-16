import assert from "node:assert/strict";
import test from "node:test";
import { highlightJava } from "../lib/java-syntax.ts";

test("Java highlighting preserves the source exactly while identifying useful syntax", () => {
  const source = `@Override\npublic String label(int count) {\n  // Keep whitespace and symbols intact.\n  return count > 1 ? "items" : "item";\n}`;
  const tokens = highlightJava(source);

  assert.equal(tokens.map((token) => token.text).join(""), source);
  for (const kind of ["annotation", "comment", "function", "keyword", "number", "string", "type"]) {
    assert.ok(tokens.some((token) => token.kind === kind), `expected a ${kind} token`);
  }
});

test("Java highlighting safely leaves unmatched code as plain text", () => {
  const source = "items.stream().map(User::name).toList();";
  assert.equal(highlightJava(source).map((token) => token.text).join(""), source);
});
