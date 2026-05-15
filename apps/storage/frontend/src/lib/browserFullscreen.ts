type FullscreenDocument = {
  exitFullscreen?: () => Promise<void> | void;
  fullscreenElement?: Element | null;
  fullscreenEnabled?: boolean;
  msExitFullscreen?: () => Promise<void> | void;
  msFullscreenElement?: Element | null;
  msFullscreenEnabled?: boolean;
  webkitExitFullscreen?: () => Promise<void> | void;
  webkitFullscreenElement?: Element | null;
  webkitFullscreenEnabled?: boolean;
};

type FullscreenElement = {
  requestFullscreen?: () => Promise<void> | void;
  msRequestFullscreen?: () => Promise<void> | void;
  webkitRequestFullscreen?: () => Promise<void> | void;
};

export function currentFullscreenElement(doc: Document = document) {
  const fullscreenDoc = doc as FullscreenDocument;
  return fullscreenDoc.fullscreenElement || fullscreenDoc.webkitFullscreenElement || fullscreenDoc.msFullscreenElement || null;
}

export function canRequestFullscreen(element: HTMLElement | null, doc: Document = document) {
  if (!element) return false;
  const fullscreenDoc = doc as FullscreenDocument;
  const fullscreenElement = element as FullscreenElement;
  const request = fullscreenElement.requestFullscreen || fullscreenElement.webkitRequestFullscreen || fullscreenElement.msRequestFullscreen;
  const enabled = fullscreenDoc.fullscreenEnabled ?? fullscreenDoc.webkitFullscreenEnabled ?? fullscreenDoc.msFullscreenEnabled;
  return Boolean(request && enabled !== false);
}

export function elementIsFullscreen(element: HTMLElement | null, doc: Document = document) {
  return Boolean(element && currentFullscreenElement(doc) === element);
}

export async function requestElementFullscreen(element: HTMLElement) {
  const fullscreenElement = element as FullscreenElement;
  const request = fullscreenElement.requestFullscreen || fullscreenElement.webkitRequestFullscreen || fullscreenElement.msRequestFullscreen;
  if (!request) throw new Error('Fullscreen is not available in this browser.');
  await request.call(element);
}

export async function exitDocumentFullscreen(doc: Document = document) {
  const fullscreenDoc = doc as FullscreenDocument;
  const exit = fullscreenDoc.exitFullscreen || fullscreenDoc.webkitExitFullscreen || fullscreenDoc.msExitFullscreen;
  if (exit) await exit.call(doc);
}
