import type { ShellThemeState } from "./theme";
import { shellThemeMessage } from "./theme";

export const MAVERICK_IFRAME_SANDBOX = "allow-downloads allow-forms allow-popups allow-popups-to-escape-sandbox allow-same-origin allow-scripts";

const CHAT_PUBLIC_APP_ID = "chat";

export function appFrameBrowserFeaturePolicy(publicAppId: string): string {
  return publicAppId === CHAT_PUBLIC_APP_ID
    ? "clipboard-write; fullscreen; microphone"
    : "fullscreen; microphone";
}

export function widgetFrameBrowserFeaturePolicy(publicAppId: string): string {
  return publicAppId === CHAT_PUBLIC_APP_ID
    ? "clipboard-write; fullscreen; microphone"
    : "fullscreen";
}

const MAX_FRAME_OWNER_ID_LENGTH = 256;
const registeredFrames = new Map<HTMLIFrameElement, string>();

export function setMaverickFrameOrigin(
  frame: HTMLIFrameElement,
  origin: string | null,
  ownerAppId: string,
) {
  if (!origin) {
    registeredFrames.delete(frame);
    delete frame.dataset.maverickFrameOrigin;
    return;
  }
  const parsed = new URL(origin);
  if (parsed.origin !== origin || origin === window.location.origin) {
    throw new Error("Maverick app frames require a distinct exact origin.");
  }
  if (!isValidFrameOwnerId(ownerAppId)) {
    throw new Error("Maverick app frames require one exact owner app id.");
  }
  frame.dataset.maverickFrameOrigin = origin;
  registeredFrames.set(frame, ownerAppId);
}

export function isMaverickFrameMessage(event: MessageEvent, frame: HTMLIFrameElement | null | undefined): boolean {
  const expectedOrigin = frame?.dataset.maverickFrameOrigin;
  return Boolean(
    frame?.contentWindow
    && expectedOrigin
    && event.source === frame.contentWindow
    && event.origin === expectedOrigin,
  );
}

export function isRegisteredMaverickFrameMessage(event: MessageEvent): boolean {
  return registeredMaverickFrameOwner(event) !== null;
}

export function registeredMaverickFrameOwner(event: MessageEvent): string | null {
  for (const [frame, ownerAppId] of registeredFrames) {
    if (isMaverickFrameMessage(event, frame)) return ownerAppId;
  }
  return null;
}

export function isMaverickOwnerMessage(event: MessageEvent, ownerAppId: string): boolean {
  return isValidFrameOwnerId(ownerAppId)
    && (isShellWindowMessage(event) || registeredMaverickFrameOwner(event) === ownerAppId);
}

export function isShellWindowMessage(event: MessageEvent): boolean {
  return event.source === window && event.origin === window.location.origin;
}

export function postToMaverickFrame(frame: HTMLIFrameElement | null | undefined, message: unknown) {
  if (!frame?.contentWindow) {
    return;
  }
  const targetOrigin = frame.dataset.maverickFrameOrigin;
  if (!targetOrigin) return;
  try {
    frame.contentWindow.postMessage(message, targetOrigin);
  } catch (error) {
    // A frame may still be on its initial about:blank document while the
    // one-shot POST navigation is in flight. Never broaden the target.
    if (error instanceof DOMException
        || (error && typeof error === "object" && (error as { name?: unknown }).name === "SecurityError")) return;
    throw error;
  }
}

export function postMaverickFrameVisibility(
  frame: HTMLIFrameElement | null | undefined,
  payload: {
    app_id?: string;
    owner_app_id?: string;
    visible: boolean;
    widget_id?: string;
  },
) {
  postToMaverickFrame(frame, {
    type: "maverick.app.visibility-changed",
    ...payload,
  });
}

export function postMaverickShellTheme(frame: HTMLIFrameElement | null | undefined, theme: ShellThemeState) {
  postToMaverickFrame(frame, shellThemeMessage(theme));
}

function isValidFrameOwnerId(value: unknown): value is string {
  return typeof value === "string"
    && value.trim() === value
    && value.length > 0
    && value.length <= MAX_FRAME_OWNER_ID_LENGTH
    && !/[\u0000-\u001f\u007f]/u.test(value);
}
