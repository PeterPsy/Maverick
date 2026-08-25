import assert from "node:assert/strict";
import test from "node:test";

import { SessionLifecycle } from "./session-lifecycle.mjs";


function lifecycleHarness({ idleTtlMs = 100, hardTtlMs = 1_000 } = {}) {
  let currentTimeMs = 0;
  const lifecycle = new SessionLifecycle({
    idleTtlMs,
    hardTtlMs,
    now: () => currentTimeMs,
  });

  function register(sessionId, { closeError = null } = {}) {
    let closeCalls = 0;
    const context = {
      async close() {
        closeCalls += 1;
        if (closeError) {
          throw closeError;
        }
      },
    };
    const session = {
      id: sessionId,
      context,
      proxyPassword: `proxy-${sessionId}`,
      policyContext: { session_id: sessionId },
      pages: new Set([{}]),
      activePage: {},
      console: [{}],
      network: [{}],
    };
    lifecycle.authorizeProxy(session.proxyPassword, session.policyContext);
    lifecycle.register(session);
    return { session, closeCalls: () => closeCalls };
  }

  return {
    lifecycle,
    register,
    setTime(value) {
      currentTimeMs = value;
    },
  };
}


test("idle expiry closes the context and removes every associated resource", async () => {
  const harness = lifecycleHarness();
  const registered = harness.register("idle-session");

  harness.setTime(100);
  const expired = await harness.lifecycle.reapExpired();

  assert.deepEqual(expired, [{ session_id: "idle-session", reason: "idle_ttl" }]);
  assert.equal(registered.closeCalls(), 1);
  assert.deepEqual(harness.lifecycle.resourceCounts(), {
    sessions: 0,
    proxy_policies: 0,
    action_queues: 0,
  });
  assert.equal(registered.session.pages.size, 0);
  assert.equal(registered.session.activePage, null);
  assert.deepEqual(registered.session.console, []);
  assert.deepEqual(registered.session.network, []);
});


test("authorized activity extends the idle deadline", async () => {
  const harness = lifecycleHarness({ idleTtlMs: 100, hardTtlMs: 1_000 });
  const registered = harness.register("active-session");

  harness.setTime(90);
  assert.equal(harness.lifecycle.touch("active-session"), true);
  harness.setTime(150);
  assert.deepEqual(await harness.lifecycle.reapExpired(), []);
  assert.equal(registered.closeCalls(), 0);

  harness.setTime(190);
  assert.deepEqual(await harness.lifecycle.reapExpired(), [{ session_id: "active-session", reason: "idle_ttl" }]);
  assert.equal(registered.closeCalls(), 1);
});


test("hard expiry cannot be extended by activity", async () => {
  const harness = lifecycleHarness({ idleTtlMs: 100, hardTtlMs: 200 });
  const registered = harness.register("hard-session");

  harness.setTime(190);
  harness.lifecycle.touch("hard-session");
  harness.setTime(200);

  assert.deepEqual(await harness.lifecycle.reapExpired(), [{ session_id: "hard-session", reason: "hard_ttl" }]);
  assert.equal(registered.closeCalls(), 1);
});


test("reaper waits for an in-flight action and rechecks its activity", async () => {
  const harness = lifecycleHarness({ idleTtlMs: 100, hardTtlMs: 1_000 });
  const registered = harness.register("queued-session");
  let releaseAction;
  const actionGate = new Promise((resolve) => {
    releaseAction = resolve;
  });
  const action = harness.lifecycle.enqueue("queued-session", async () => {
    await actionGate;
    harness.lifecycle.touch("queued-session");
  });
  await Promise.resolve();

  harness.setTime(100);
  const reaping = harness.lifecycle.reapExpired();
  harness.setTime(110);
  releaseAction();

  await action;
  assert.deepEqual(await reaping, []);
  assert.equal(registered.closeCalls(), 0);
  assert.equal(harness.lifecycle.resourceCounts().sessions, 1);
  assert.equal(harness.lifecycle.resourceCounts().action_queues, 0);
});


test("explicit close drains its queue and cleans maps even if context close fails", async () => {
  const harness = lifecycleHarness();
  const registered = harness.register("close-session", { closeError: new Error("already disconnected") });

  await harness.lifecycle.enqueue("close-session", async () => {
    await harness.lifecycle.closeRegisteredSession(registered.session, { reason: "explicit" });
  });

  assert.equal(registered.closeCalls(), 1);
  assert.deepEqual(harness.lifecycle.resourceCounts(), {
    sessions: 0,
    proxy_policies: 0,
    action_queues: 0,
  });
});


test("closeAll leaves no registered or orphaned session resources", async () => {
  const harness = lifecycleHarness();
  const first = harness.register("first-session");
  const second = harness.register("second-session");

  await harness.lifecycle.closeAll({ reason: "shutdown" });

  assert.equal(first.closeCalls(), 1);
  assert.equal(second.closeCalls(), 1);
  assert.deepEqual(harness.lifecycle.resourceCounts(), {
    sessions: 0,
    proxy_policies: 0,
    action_queues: 0,
  });
});
