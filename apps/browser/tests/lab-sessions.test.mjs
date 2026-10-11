import test from "node:test";
import assert from "node:assert/strict";
import {activeLabSessions} from "../frontend/src/lab-sessions.js";

test("management omits expired records while recent observations extend the idle deadline", () => {
  const now = Date.parse("2026-10-11T12:00:00Z"), lifecycle = {idle_ttl_ms: 15 * 60000, hard_ttl_ms: 4 * 3600000};
  const session = {created_at: "2026-10-11T10:00:00Z", updated_at: "2026-10-11T11:59:00Z",
    last_activity_at: "2026-10-11T10:00:00Z", idle_expires_at: "2026-10-11T10:15:00Z", hard_expires_at: "2026-10-11T14:00:00Z"};
  const expired = {...session, updated_at: "2026-10-11T11:00:00Z"};
  const hardExpired = {...session, hard_expires_at: "2026-10-11T11:00:00Z"};
  assert.deepEqual(activeLabSessions([session, expired, hardExpired, {}], lifecycle, now), [session]);
  const recorded = {created_at: "2026-10-11T10:00:00Z", updated_at: "2026-10-11T11:59:00Z"};
  assert.deepEqual(activeLabSessions([recorded], lifecycle, now), [recorded]);
  assert.deepEqual(activeLabSessions([recorded], {}, now), []);
});
