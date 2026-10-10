/** Private Core-issued authentication for an ephemeral Maverick context. */
export function isPlatformTarget(rawUrl, policy) {
  if (!policy?.platform_origin) return false;
  try {
    const target = new URL(rawUrl);
    const platform = new URL(policy.platform_origin);
    if (target.username || target.password || target.protocol !== platform.protocol || target.port !== platform.port) return false;
    if (target.hostname === platform.hostname) return true;
    const suffix = policy.frame_host_suffix || `.sidecars.${platform.hostname}`;
    return target.hostname.endsWith(suffix) && /^af-[0-9a-f]{24}$/.test(target.hostname.slice(0, -suffix.length));
  } catch { return false; }
}

export function privatePlatformGrant(payload, now = Date.now()) {
  const grant = payload.platform_browser_session;
  if (!grant) return null;
  const caller = payload.caller_context || {};
  let origin;
  try { origin = new URL(grant.origin); } catch { throw new Error("Invalid platform browser origin."); }
  if (origin.origin !== grant.origin || origin.username || origin.password ||
      !["http:", "https:"].includes(origin.protocol) ||
      (origin.protocol === "http:" && origin.hostname !== "maverick.localhost") ||
      grant.cookie_name !== "maverick_session" || !/^[0-9a-f-]{36}$/.test(grant.cookie_value || "") ||
      !Number.isFinite(grant.expires_at) || grant.expires_at * 1000 <= now || grant.expires_at * 1000 > now + 4 * 60 * 60 * 1000 ||
      !grant.user_id || grant.user_id !== caller.user_id || !grant.workspace_id || grant.workspace_id !== caller.workspace_id ||
      !/^\.sidecars\.[a-z0-9.-]+$/.test(grant.frame_host_suffix || "")) {
    throw new Error("Invalid platform browser authentication binding.");
  }
  return { ...grant };
}

export async function installPlatformAuthentication(context, grant) {
  if (!grant) return;
  await context.addCookies([{
    name: grant.cookie_name, value: grant.cookie_value, url: grant.origin,
    httpOnly: true, sameSite: "Lax", secure: grant.origin.startsWith("https:"), expires: grant.expires_at,
  }]);
}

export async function releasePlatformAuthentication(session) {
  const grant = session.platformAuthentication;
  if (!grant) return;
  try {
    await session.context.request.post(`${grant.origin}/api/auth/logout`, {
      headers: { Origin: grant.origin, "Sec-Fetch-Site": "same-origin" }, timeout: 5000,
    });
  } catch {
    // The fixed expiry and Core's live actor/workspace/runtime checks remain in force.
  } finally {
    grant.cookie_value = "";
    session.platformAuthentication = null;
  }
}

export function assertBrowserOwner(session, payload) {
  const caller = payload.caller_context || {};
  if ((session.userId && session.userId !== caller.user_id) ||
      (session.workspaceId && session.workspaceId !== caller.workspace_id)) {
    const error = new Error("Browser session belongs to another user or workspace.");
    error.statusCode = 403;
    error.code = "session_forbidden";
    throw error;
  }
}
