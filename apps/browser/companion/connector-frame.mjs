import {connectorFrameUrl, sameConnector} from "./scope.mjs";

// Probe only app identity in the selected shell tab, then bind one exact document.
export async function attachConnectorFrame(b, currentBinding) {
  if (!sameConnector(await chrome.tabs.get(b.connectorTabId), b)) throw new Error("connector_left_browser");
  const frames = await chrome.scripting.executeScript({
    target: {tabId: b.connectorTabId, allFrames: true}, world: "MAIN",
    func: () => {
      if (window.__MAVERICK_APP_FRAME_CONTEXT__?.app_id !== "browser") return null;
      return {url: location.href, platformOrigin: window.__MAVERICK_PLATFORM_ORIGIN__};
    },
  });
  const selected = frames.filter(frame => frame.result?.platformOrigin === b.origin && connectorFrameUrl(frame.result.url, b.origin, b.frameDomain));
  if (selected.length !== 1) return {status: "waiting_for_browser"};
  const frame = selected[0], current = await currentBinding();
  if (current?.sharingId !== b.sharingId || !sameConnector(await chrome.tabs.get(b.connectorTabId), b)) throw new Error("sharing_revoked");
  const {connectorSession}=await chrome.storage.session.get("connectorSession");
  if(connectorSession?.sharingId === b.sharingId && connectorSession.lease && connectorSession.origin !== new URL(frame.result.url).origin)throw new Error("connector_principal_changed");
  if (!frame.documentId) throw new Error("connector_document_unavailable");
  const binding = {...current, connectorFrameId: frame.frameId, connectorDocumentId: frame.documentId,
    connectorFrameOrigin: new URL(frame.result.url).origin};
  await chrome.storage.session.set({binding});
  await chrome.scripting.executeScript({target: {tabId: b.connectorTabId, documentIds: [frame.documentId]}, files: ["content.js"]});
  return {status: "attached", binding};
}
