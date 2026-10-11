// The user's Connect action may bring any existing Maverick shell to Browser.
const isShell = (value, origin) => {
  try {
    const url = new URL(value);
    return url.origin === origin && !url.username && !url.password
      && (url.pathname === "/" || /^\/app(?:\/|$)/u.test(url.pathname));
  } catch {return false;}
};
export async function openConnectorWindow(url, {sourceTabId, reuse = true} = {}) {
  if (reuse) {
    const tabs = await chrome.tabs.query({url: `${url.origin}/*`});
    const candidates = tabs.filter(tab => tab.id !== sourceTabId && isShell(tab.url, url.origin))
      .sort((a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0));
    for (const tab of candidates) {
      // A tab can close between discovery and selection. Recheck before navigating.
      let current;
      try { current = await chrome.tabs.get(tab.id); } catch { continue; }
      if (!isShell(current.url, url.origin)) continue;
      const connector = await chrome.tabs.update(tab.id, {url: url.href, active: true});
      await chrome.windows.update(connector.windowId, {focused: true});
      return connector;
    }
  }
  const window = await chrome.windows.create({url: url.href, type: "popup", width: 1040, height: 850});
  return window.tabs[0];
}
