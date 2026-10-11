import {platformUrl, platformForUrl} from "./scope.mjs";

export function shareableTab(tab) {
  if (!Number.isInteger(tab?.id) || typeof tab.url !== "string") throw new Error("active_tab_unavailable");
  const url = platformUrl(tab.url);
  return {id: tab.id, url, title: tab.title || platformForUrl(url)};
}

export function setupError(error) {
  const code = error?.message || "";
  if (["active_tab_unavailable", "invalid_platform_url", "shared_platform_scope_required"].includes(code))
    return "Open an Instagram profile or another supported platform page in Chrome, then click this extension on that tab. Chrome settings, the Extensions page and Maverick cannot be shared.";
  if (["platform_route_unavailable", "platform_query_limit"].includes(code))
    return "Open a profile, post or video on a supported platform. Sign-in, messages and settings pages cannot be shared.";
  if (["browser_connector_url_required", "secure_connector_url_required", "invalid_frame_domain"].includes(code) || error instanceof TypeError)
    return "Copy the connector address from Browser in Maverick and paste it here. It must end with /app/browser?connector=1.";
  if (code === "permission_denied") return "Allow access to Maverick and the selected platform when Chrome asks, then share the tab again.";
  return code || "Sharing could not start. Reload the extension in chrome://extensions and try again from the platform tab.";
}
