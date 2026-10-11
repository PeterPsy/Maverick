// Reuse only Browser in the chosen Chrome profile and Maverick origin.
export async function openConnectorWindow(url, {sourceTabId, reuse = true} = {}) {
  if (reuse) {
    const tabs = await chrome.tabs.query({url: `${url.origin}/app/browser*`});
    const candidates = tabs.filter(tab => {
      try {
        const current = new URL(tab.url);
        return tab.id !== sourceTabId && current.origin === url.origin && current.pathname === "/app/browser";
      } catch { return false; }
    }).sort((a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0));
    for (const tab of candidates) {
      // A tab can close between discovery and selection. Recheck before navigating.
      let current;
      try { current = await chrome.tabs.get(tab.id); } catch { continue; }
      try {
        const address = new URL(current.url);
        if (address.origin !== url.origin || address.pathname !== "/app/browser") continue;
      } catch { continue; }
      const connector = await chrome.tabs.update(tab.id, {url: url.href, active: true});
      await chrome.windows.update(connector.windowId, {focused: true});
      return connector;
    }
  }
  const window = await chrome.windows.create({url: url.href, type: "popup", width: 1040, height: 850});
  return window.tabs[0];
}
