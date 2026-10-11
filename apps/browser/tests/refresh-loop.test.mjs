import test from "node:test";
import assert from "node:assert/strict";
import {createRefreshLoop, overviewDelay} from "../frontend/src/refresh-loop.js";

function fixture(read, options = {}) {
  const scheduled = [], errors = [];
  const loop = createRefreshLoop({read, delay: () => 30000, visible: () => true,
    schedule(fn, wait) { const timer = {fn, wait}; scheduled.push(timer); return timer; },
    cancel(timer) { if (timer) scheduled.splice(scheduled.indexOf(timer), 1); },
    onError: error => errors.push(error), ...options});
  return {loop, scheduled, errors};
}

test("slow reads never overlap and changes coalesce into one trailing update", async () => {
  let release, reads = 0;
  const {loop, scheduled} = fixture(() => { reads++; return new Promise(resolve => { release = resolve; }); });
  const first = loop.refresh(); await Promise.resolve();
  assert.equal(loop.refresh(), first); assert.equal(loop.refresh(), first);
  assert.equal(reads, 1); release(); await first;
  assert.equal(scheduled.length, 1); assert.equal(scheduled[0].wait, 0);
  const trailing = scheduled[0].fn(); await Promise.resolve();
  assert.equal(reads, 2); release(); await trailing;
  assert.equal(scheduled.length, 1); assert.equal(scheduled[0].wait, 30000);
  loop.stop(); assert.equal(scheduled.length, 0);
});

test("hidden pages pause polling and shutdown aborts the pending read", async () => {
  let shown = false, signal, release;
  const {loop, scheduled} = fixture(value => { signal = value; return new Promise(resolve => { release = resolve; }); }, {visible: () => shown});
  await loop.refresh(); assert.equal(signal, undefined);
  shown = true; const pending = loop.refresh(); await Promise.resolve();
  loop.stop(); assert.equal(signal.aborted, true); release(); await pending;
  assert.equal(scheduled.length, 0);
});

test("failed reads back off and a successful retry restores the regular interval", async () => {
  let broken = true;
  const {loop, scheduled, errors} = fixture(() => { if (broken) throw new Error("offline"); });
  await loop.refresh(); assert.equal(errors.length, 1); assert.equal(scheduled[0].wait, 5000);
  await loop.refresh(); assert.equal(scheduled[0].wait, 10000);
  broken = false; await loop.refresh(); assert.equal(scheduled[0].wait, 30000); loop.stop();
});

test("pending media and active tabs get timely updates while idle views do less work", () => {
  assert.equal(overviewDelay({connections: [], operations: []}), 30000);
  assert.equal(overviewDelay({connections: [{status: "connected"}], operations: []}), 10000);
  assert.equal(overviewDelay({connections: [], operations: [{status: "processing_media"}]}), 3000);
  assert.equal(overviewDelay({connections: [], operations: [], pending_count: 48}), 3000);
});
