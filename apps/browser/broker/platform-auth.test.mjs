import assert from "node:assert/strict";
import test from "node:test";
import { isPlatformTarget, privatePlatformGrant, installPlatformAuthentication, releasePlatformAuthentication, assertBrowserOwner } from "./platform-auth.mjs";
import { SessionLifecycle } from "./session-lifecycle.mjs";

const now = 1_000_000;
function payload() {
  return { caller_context: { user_id: "user:one", workspace_id: "default" }, platform_browser_session: {
    origin: "http://maverick.localhost:8014", frame_host_suffix: ".sidecars.maverick.localhost",
    cookie_name: "maverick_session", cookie_value: "00000000-0000-4000-8000-000000000001",
    expires_at: (now + 4 * 60 * 60 * 1000) / 1000, user_id: "user:one", workspace_id: "default",
  } };
}

test("private authentication accepts only a live bounded grant for its actor and workspace", () => {
  assert.equal(privatePlatformGrant(payload(), now).origin, "http://maverick.localhost:8014");
  for (const patch of [{ user_id: "user:two" }, { workspace_id: "another" }, { expires_at: now / 1000 },
    { expires_at: (now + 5 * 60 * 60 * 1000) / 1000 }, { origin: "http://example.com" },
    { origin: "http://maverick.localhost:8014/path" }, { cookie_name: "another" }]) {
    const input = payload(); Object.assign(input.platform_browser_session, patch);
    assert.throws(() => privatePlatformGrant(input, now));
  }
});

test("a delegated policy permits only the exact platform and generated app frames", () => {
  const policy = { platform_origin: payload().platform_browser_session.origin, frame_host_suffix: ".sidecars.maverick.localhost" };
  assert.ok(isPlatformTarget("http://maverick.localhost:8014/app/chat", policy));
  assert.ok(isPlatformTarget(`http://af-${"a".repeat(24)}.sidecars.maverick.localhost:8014/api/session`, policy));
  for (const url of ["http://hostmachine:8014", "http://maverick.localhost:8000", "https://maverick.localhost:8014",
    "http://maverick.localhost.evil.test:8014", "http://other.sidecars.maverick.localhost:8014",
    "http://user:secret@maverick.localhost:8014"]) assert.equal(isPlatformTarget(url, policy), false, url);
});

test("cookies are host scoped and HttpOnly and do not use a persistent profile", async () => {
  let cookies;
  await installPlatformAuthentication({ addCookies: async value => { cookies = value; } }, payload().platform_browser_session);
  assert.equal(cookies.length, 1);
  assert.equal(cookies[0].url, "http://maverick.localhost:8014");
  assert.equal(cookies[0].domain, undefined);
  assert.equal(cookies[0].httpOnly, true);
  assert.equal(cookies[0].sameSite, "Lax");
});

test("other agents of the same user can use the session; other actors and workspaces cannot", () => {
  const session = { userId: "user:one", workspaceId: "default" };
  assertBrowserOwner(session, payload());
  for (const caller_context of [{ user_id: "user:two", workspace_id: "default" }, { user_id: "user:one", workspace_id: "another" }]) {
    assert.throws(() => assertBrowserOwner(session, { caller_context }), error => error.statusCode === 403);
  }
});

test("expiry and explicit close release the login before destroying the proxy and context", async () => {
  for (const expired of [false, true]) {
    let time = now, closed = false, loggedOut = false;
    const lifecycle = new SessionLifecycle({ idleTtlMs: 100, hardTtlMs: 1000, now: () => time });
    const session = { id: "session", proxyPassword: "proxy", platformAuthentication: payload().platform_browser_session,
      context: { request: { post: async (url, options) => {
        assert.ok(lifecycle.proxyPolicy("proxy"));
        assert.equal(url, "http://maverick.localhost:8014/api/auth/logout");
        assert.equal(options.headers.Origin, "http://maverick.localhost:8014"); loggedOut = true;
      } }, close: async () => { assert.ok(loggedOut); closed = true; } } };
    session.beforeClose = () => releasePlatformAuthentication(session);
    lifecycle.authorizeProxy("proxy", {}); lifecycle.register(session);
    if (expired) { time += 101; await lifecycle.reapExpired(); }
    else await lifecycle.closeRegisteredSession(session, { reason: "explicit" });
    assert.ok(closed); assert.equal(session.platformAuthentication, null);
    assert.equal(lifecycle.proxyPolicy("proxy"), undefined);
  }
});
