function requirePositiveDuration(value, field) {
  if (!Number.isFinite(value) || value <= 0) {
    throw new TypeError(`${field} must be a positive duration in milliseconds.`);
  }
  return Math.trunc(value);
}


function clearSessionReferences(session) {
  session.pages?.clear?.();
  session.activePage = null;
  if (Array.isArray(session.console)) {
    session.console.length = 0;
  }
  if (Array.isArray(session.network)) {
    session.network.length = 0;
  }
}


export class SessionLifecycle {
  constructor({ idleTtlMs, hardTtlMs, now = Date.now, onContextCloseError = () => undefined }) {
    this.idleTtlMs = requirePositiveDuration(idleTtlMs, "idleTtlMs");
    this.hardTtlMs = requirePositiveDuration(hardTtlMs, "hardTtlMs");
    if (typeof now !== "function") {
      throw new TypeError("now must be a function.");
    }
    if (typeof onContextCloseError !== "function") {
      throw new TypeError("onContextCloseError must be a function.");
    }
    this.now = now;
    this.onContextCloseError = onContextCloseError;
    this.sessions = new Map();
    this.proxyPolicies = new Map();
    this.actionQueues = new Map();
  }

  authorizeProxy(proxyPassword, policyContext) {
    this.proxyPolicies.set(proxyPassword, policyContext);
  }

  revokeProxy(proxyPassword) {
    this.proxyPolicies.delete(proxyPassword);
  }

  proxyPolicy(proxyPassword) {
    return this.proxyPolicies.get(proxyPassword);
  }

  register(session) {
    if (!session || typeof session.id !== "string" || !session.id) {
      throw new TypeError("A Browser session id is required.");
    }
    if (!session.context || typeof session.context.close !== "function") {
      throw new TypeError("A Browser context with close() is required.");
    }
    if (!session.proxyPassword || !this.proxyPolicies.has(session.proxyPassword)) {
      throw new TypeError("A registered Browser proxy policy is required.");
    }
    if (this.sessions.has(session.id)) {
      throw new Error(`Browser session is already registered: ${session.id}.`);
    }
    const timestamp = this.now();
    session.createdAtMs = timestamp;
    session.lastActivityAtMs = timestamp;
    this.sessions.set(session.id, session);
    return session;
  }

  getSession(sessionId) {
    return this.sessions.get(sessionId);
  }

  touch(sessionOrId) {
    const sessionId = typeof sessionOrId === "string" ? sessionOrId : sessionOrId?.id;
    const session = this.sessions.get(sessionId);
    if (!session || (typeof sessionOrId === "object" && session !== sessionOrId)) {
      return false;
    }
    session.lastActivityAtMs = Math.max(session.createdAtMs, session.lastActivityAtMs, this.now());
    return true;
  }

  timingPayload(session) {
    return {
      created_at: new Date(session.createdAtMs).toISOString(),
      last_activity_at: new Date(session.lastActivityAtMs).toISOString(),
      idle_expires_at: new Date(session.lastActivityAtMs + this.idleTtlMs).toISOString(),
      hard_expires_at: new Date(session.createdAtMs + this.hardTtlMs).toISOString(),
    };
  }

  expirationReason(session, timestamp = this.now()) {
    if (timestamp - session.createdAtMs >= this.hardTtlMs) {
      return "hard_ttl";
    }
    if (timestamp - session.lastActivityAtMs >= this.idleTtlMs) {
      return "idle_ttl";
    }
    return null;
  }

  enqueue(sessionId, operation) {
    const key = String(sessionId).trim();
    const previous = this.actionQueues.get(key) || Promise.resolve();
    const result = previous.catch(() => undefined).then(operation);
    let tracked;
    tracked = result.finally(() => {
      if (this.actionQueues.get(key) === tracked) {
        this.actionQueues.delete(key);
      }
    });
    this.actionQueues.set(key, tracked);
    return tracked;
  }

  async closeRegisteredSession(session, { reason }) {
    if (this.sessions.get(session.id) !== session) {
      return false;
    }
    this.sessions.delete(session.id);
    this.revokeProxy(session.proxyPassword);
    session.closedAtMs = this.now();
    session.closeReason = reason;
    try {
      await session.context.close();
    } catch (error) {
      try {
        this.onContextCloseError(error, session, reason);
      } catch {
        // Cleanup must not fail because an observer failed.
      }
    } finally {
      clearSessionReferences(session);
    }
    return true;
  }

  async reapExpired() {
    const candidates = [...this.sessions.values()].filter((session) => this.expirationReason(session) !== null);
    const results = await Promise.all(
      candidates.map((candidate) =>
        this.enqueue(candidate.id, async () => {
          const session = this.sessions.get(candidate.id);
          if (!session) {
            return null;
          }
          const reason = this.expirationReason(session);
          if (!reason) {
            return null;
          }
          await this.closeRegisteredSession(session, { reason });
          return { session_id: session.id, reason };
        }),
      ),
    );
    return results.filter((result) => result !== null);
  }

  async closeAll({ reason }) {
    const sessionIds = [...this.sessions.keys()];
    await Promise.all(
      sessionIds.map((sessionId) =>
        this.enqueue(sessionId, async () => {
          const session = this.sessions.get(sessionId);
          if (session) {
            await this.closeRegisteredSession(session, { reason });
          }
        }),
      ),
    );
  }

  discardDisconnected({ reason }) {
    const timestamp = this.now();
    for (const session of this.sessions.values()) {
      session.closedAtMs = timestamp;
      session.closeReason = reason;
      clearSessionReferences(session);
    }
    this.sessions.clear();
    this.proxyPolicies.clear();
    this.actionQueues.clear();
  }

  resourceCounts() {
    return {
      sessions: this.sessions.size,
      proxy_policies: this.proxyPolicies.size,
      action_queues: this.actionQueues.size,
    };
  }
}
