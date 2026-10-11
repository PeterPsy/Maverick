export function activeLabSessions(sessions, lifecycle = {}, now = Date.now()) {
  return sessions.filter(session => {
    const created = Date.parse(session.created_at);
    const activity = Math.max(...[session.last_activity_at, session.updated_at, session.created_at]
      .map(value => Date.parse(value)).filter(Number.isFinite));
    // Backend observations record activity even when the broker response is just content.
    const idle = Number.isFinite(activity) && lifecycle.idle_ttl_ms > 0 ? activity + lifecycle.idle_ttl_ms : Date.parse(session.idle_expires_at);
    const hard = Date.parse(session.hard_expires_at) || (created + lifecycle.hard_ttl_ms);
    return Number.isFinite(idle) && Number.isFinite(hard) && idle > now && hard > now;
  });
}
