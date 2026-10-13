// The user's Connect action may bring any existing Maverick shell to Browser.
const isShell = (value, origin) => {
  try {
    const url = new URL(value);
    return url.origin === origin && !url.username && !url.password
      && (url.pathname === "/" || /^\/app(?:\/|$)/u.test(url.pathname) || ["/apps/base-shell/","/apps/base-shell/index.html"].includes(url.pathname));
  } catch {return false;}
};
export async function openConnectorWindow(url, {sourceTabId, reuse = true} = {}) {
  if (reuse) {
    // Include loading/PWA windows: URL-pattern queries can miss a pending shell.
    // Only exact-origin shell URLs survive; other page metadata is never retained.
    const tabs = await chrome.tabs.query({});
    const windows=await chrome.windows.getAll({windowTypes:["normal","popup"]});
    const normal=new Set(windows.filter(w=>w.type === "normal").map(w=>w.id));
    const candidates = tabs.filter(tab => tab.id !== sourceTabId && isShell(tab.pendingUrl || tab.url, url.origin))
      .sort((a, b) => Number(normal.has(b.windowId))-Number(normal.has(a.windowId)) || (b.lastAccessed || 0)-(a.lastAccessed || 0));
    for (const tab of candidates) {
      // A tab can close between discovery and selection. Recheck before navigating.
      let current;
      try { current = await chrome.tabs.get(tab.id); } catch { continue; }
      if (!isShell(current.pendingUrl || current.url, url.origin)) continue;
      const connector = await chrome.tabs.update(tab.id, {url: url.href, active: true});
      await chrome.windows.update(connector.windowId, {focused: true});
      return connector;
    }
    // Fresh setup uses the existing Chrome window rather than a Maverick popup.
    const target=windows.filter(w=>w.type === "normal").sort((a,b)=>Number(b.focused)-Number(a.focused))[0];
    if(target) {
      const connector=await chrome.tabs.create({windowId:target.id,url:url.href,active:true});
      await chrome.windows.update(target.id,{focused:true});return connector;
    }
  }
  const window = await chrome.windows.create({url: url.href, type: "popup", width: 1040, height: 850});
  return window.tabs[0];
}
