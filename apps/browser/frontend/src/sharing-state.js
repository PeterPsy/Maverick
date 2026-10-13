export const stopReasons = {
  user_stopped: "Sharing stopped by the user",
  connector_scope_required: "The Browser connection document changed; connect again from Companion",
  sharing_revoked: "Chrome sharing ended; keep the shared tab and Browser bridge open",
  extension_unavailable: "Chrome could not reach Companion; reload the extension and reconnect",
  companion_unavailable: "The selected tab is no longer attached to this Browser window",
  platform_route_unavailable: "The shared tab left the supported content routes",
  connection_expired: "The Browser connection expired; reconnect from Companion",
  connection_revoked: "The Browser connection was stopped",
  connection_replaced: "Replaced by a new connection for this agent tab",
  connection_unavailable: "The connection is unavailable for this Maverick account or workspace",
  connector_unauthorized: "The Browser bridge lease is invalid; reconnect from Companion",
  authentication_failed: "Maverick authentication expired; sign in in the Browser bridge and reconnect",
  connector_principal_changed: "The connected Maverick account or workspace changed; reconnect from Companion",
  heartbeat_failed: "The Browser bridge could not maintain its connection; reconnect from Companion",
};

export function stopReason(error) {
  if (!error) return "user_stopped";
  if (["shared_platform_scope_required", "invalid_platform_url","website_scope_required","invalid_website_url"].includes(error.code)) return "platform_route_unavailable";
  if (Object.hasOwn(stopReasons, error.code)) return error.code;
  return [401, 403].includes(error.status) ? "authentication_failed" : "heartbeat_failed";
}

export function connectionDetail(connection) {
  const mode = connection.access_mode === "interactive" ? "Agent tab · Interactive" : connection.sharing_mode === "agent_tab" ? "Agent tab · Read only" : connection.platform || "Chrome";
  if (connection.status === "revoked") return `${mode} · ${Object.hasOwn(stopReasons, connection.stop_reason) ? stopReasons[connection.stop_reason] : "Sharing stopped; reconnect from Companion"}`;
  if (connection.status === "offline") return `${mode} · Bridge offline; reopen Browser and reconnect from Companion`;
  return `${mode} · ${connection.url || (connection.sharing_mode === "agent_tab" ? "Ready for agent navigation" : "Waiting for Chrome to share a page")}`;
}
