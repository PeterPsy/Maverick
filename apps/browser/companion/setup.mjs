import {sharedTabUrl} from "./scope.mjs";
import {platforms} from "./platforms.mjs";

// Official Maverick installation. Other installations can change Connection settings.
export const defaultConnectorUrl = "https://maverick.loopino.ai/app/browser?connector=1";

export function selectedAgentTab(tab, agentTabUrl, identity) {
  if (!Number.isInteger(tab?.id) || typeof tab.url !== "string") throw new Error("active_tab_unavailable");
  if (tab.url === agentTabUrl) return {id:tab.id, url:"", title:"Maverick agent tab", allowed_platforms:Object.keys(platforms)};
  if (identity?.tabId === tab.id && identity.allowedPlatforms?.length) {
    return {id:tab.id, url:sharedTabUrl(tab.url, identity, agentTabUrl), title:tab.title || "Agent tab", allowed_platforms:identity.allowedPlatforms, reconnect:true};
  }
  throw new Error("agent_tab_required");
}

export function setupError(error) {
  const code = error?.message || "";
  if (["agent_tab_required", "active_tab_unavailable", "invalid_platform_url", "shared_platform_scope_required"].includes(code))
    return "Choose Open agent tab, then click Companion in Chrome’s toolbar on that tab to connect it.";
  if (["platform_route_unavailable", "platform_query_limit"].includes(code))
    return "Return the agent tab to a supported platform home page, profile, post or video, then reconnect. Sign-in, messages and settings pages require you to act directly in Chrome.";
  if (["browser_connector_url_required", "secure_connector_url_required", "invalid_frame_domain"].includes(code) || error instanceof TypeError)
    return "Check the Maverick address in Connection settings. For another installation, use its Browser connector address ending with /app/browser?connector=1.";
  if (code === "permission_denied") return "Allow access to Maverick and the supported platforms when Chrome asks, then connect the agent tab again.";
  return code || "The agent tab could not connect. Reload the extension in chrome://extensions and try again on the agent tab.";
}
