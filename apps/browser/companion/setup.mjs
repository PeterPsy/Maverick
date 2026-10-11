import {platformUrl, platformForUrl} from "./scope.mjs";
import {platforms} from "./platforms.mjs";

// Official Maverick installation. Other installations can change Connection settings.
export const defaultConnectorUrl = "https://maverick.loopino.ai/app/browser?connector=1";

export function shareableTab(tab, agentTabUrl) {
  if (!Number.isInteger(tab?.id) || typeof tab.url !== "string") throw new Error("active_tab_unavailable");
  if (agentTabUrl && tab.url === agentTabUrl) return {id:tab.id, url:"", title:"Maverick agent tab", allowed_platforms:Object.keys(platforms)};
  const url = platformUrl(tab.url);
  return {id: tab.id, url, title: tab.title || platformForUrl(url)};
}

export function setupError(error) {
  const code = error?.message || "";
  if (["active_tab_unavailable", "invalid_platform_url", "shared_platform_scope_required"].includes(code))
    return "Open a supported platform page, then click this extension on that tab. Or choose Open agent tab below to start from an empty, dedicated tab.";
  if (["platform_route_unavailable", "platform_query_limit"].includes(code))
    return "Open a platform home page, profile, post or video. Sign-in, messages and settings pages cannot be shared.";
  if (["browser_connector_url_required", "secure_connector_url_required", "invalid_frame_domain"].includes(code) || error instanceof TypeError)
    return "Check the Maverick address in Connection settings. For another installation, use its Browser connector address ending with /app/browser?connector=1.";
  if (code === "permission_denied") return "Allow access to Maverick and the selected platform when Chrome asks, then share the tab again.";
  return code || "Sharing could not start. Reload the extension in chrome://extensions and try again from the platform tab.";
}
