import {connectorUrl, connectorOrigins} from "./scope.mjs";
import {platforms} from "./platforms.mjs";

// The service worker owns the whole transaction: Chrome may close the popup
// while its permission dialog is open. Request before any await to keep the gesture.
export function createShareSetup(share) {
  let starting;
  return message => {
    if (starting) return starting;
    try {
      const url = connectorUrl(message.url);
      const agentTab = message.agentTab === true;
      if (!Number.isInteger(message.tabId) || !agentTab && !Object.hasOwn(platforms, message.platform)) throw new Error("shared_platform_scope_required");
      const approved = agentTab ? Object.keys(platforms) : [message.platform];
      const origins = [...connectorOrigins(url), ...approved.flatMap(key => platforms[key].hosts.map(host => `https://${host}/*`))];
      starting = chrome.permissions.request({origins}).then(granted => {
        if (!granted) throw new Error("permission_denied");
        return share({...message, url: url.href});
      }).finally(() => {starting = null;});
      return starting;
    } catch (error) {return Promise.reject(error);}
  };
}
