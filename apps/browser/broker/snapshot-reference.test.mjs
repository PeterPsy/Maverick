import assert from "node:assert/strict";
import test from "node:test";
import { snapshotReferenceSelector } from "./snapshot-reference.mjs";

test("AI snapshot refs resolve through Playwright's reference engine", () => {
  assert.equal(snapshotReferenceSelector(" e20 "), "aria-ref=e20");
  assert.equal(snapshotReferenceSelector("e1"), "aria-ref=e1");
  assert.equal(snapshotReferenceSelector("f1e25"), "aria-ref=f1e25");
});

test("explicit operator selectors and already normalized refs retain their meaning", () => {
  assert.equal(snapshotReferenceSelector("aria-ref=e20"), "aria-ref=e20");
  assert.equal(snapshotReferenceSelector("#email"), "#email");
});
