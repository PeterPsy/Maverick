// Only the user-selected /app/browser connector window receives this observer.
if (!globalThis.loopinoConnectorShellInstalled) {
  globalThis.loopinoConnectorShellInstalled = true;
  let timer;
  const refresh = () => {
    clearTimeout(timer);
    timer = setTimeout(() => chrome.runtime.sendMessage({target: "worker", action: "connector.refresh"}).catch(() => {}), 250);
  };
  document.addEventListener("load", event => { if (event.target instanceof HTMLIFrameElement) refresh(); }, true);
  new MutationObserver(records => {
    if (records.some(record => [...record.addedNodes].some(node => node.nodeType === 1 && (node.tagName === "IFRAME" || node.querySelector("iframe"))))) refresh();
  }).observe(document.documentElement, {childList: true, subtree: true});
  refresh();
}
