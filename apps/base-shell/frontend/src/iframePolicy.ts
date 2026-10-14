import type { ShellThemeState } from "./theme";
import { shellThemeMessage } from "./theme";

export const LOOPINO_IFRAME_SANDBOX = "allow-downloads allow-forms allow-popups allow-popups-to-escape-sandbox allow-same-origin allow-scripts";

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

/** A srcdoc/form launch has no isolated iframe src to use as the default allowlist. */
export function isolatedFrameBrowserFeaturePolicy(features: string | undefined, origin: string | null): string | undefined {
  return features?.split(";")
    .map((feature) => feature.trim())
    .filter(Boolean)
    .map((feature) => `${feature} ${origin || "'none'"}`)
    .join("; ");
}

const MAX_FRAME_OWNER_ID_LENGTH = 256;
const MAX_FRAME_SCOPE_ID_LENGTH = 256;

export type LoopinoFrameScope = Readonly<{
  sessionGeneration: string;
  workspaceId: string;
}>;

export type RegisteredLoopinoFrameIdentity = Readonly<{
  ownerAppId: string;
  scope: LoopinoFrameScope;
}>;

const registeredFrames = new Map<HTMLIFrameElement, RegisteredLoopinoFrameIdentity>();
const frameRegistryListeners = new Set<() => void>();
let frameRegistryRevision = 0;

export function subscribeLoopinoFrameRegistry(listener: () => void): () => void {
  frameRegistryListeners.add(listener);
  return () => { frameRegistryListeners.delete(listener); };
}

export function loopinoFrameRegistryRevision(): number {
  return frameRegistryRevision;
}

export function registeredLoopinoAppIds(scope: LoopinoFrameScope): string[] {
  return [...new Set([...registeredFrames]
    .filter(([frame, identity]) => frame.isConnected && sameLoopinoFrameScope(identity.scope, scope))
    .map(([, identity]) => identity.ownerAppId))];
}

function notifyFrameRegistryChanged() {
  frameRegistryRevision += 1;
  for (const listener of frameRegistryListeners) listener();
}

export function setLoopinoFrameOrigin(
  frame: HTMLIFrameElement,
  origin: string | null,
  ownerAppId: string,
  scope: LoopinoFrameScope,
) {
  if (!origin) {
    const removed = registeredFrames.delete(frame);
    delete frame.dataset.loopinoFrameOrigin;
    if (removed) notifyFrameRegistryChanged();
    return;
  }
  const parsed = new URL(origin);
  if (parsed.origin !== origin || origin === window.location.origin) {
    throw new Error("Loopino app frames require a distinct exact origin.");
  }
  if (!isValidFrameOwnerId(ownerAppId)) {
    throw new Error("Loopino app frames require one exact owner app id.");
  }
  if (!isValidFrameScope(scope)) {
    throw new Error("Loopino app frames require one exact workspace/session scope.");
  }
  frame.dataset.loopinoFrameOrigin = origin;
  registeredFrames.set(frame, Object.freeze({
    ownerAppId,
    scope: Object.freeze({ ...scope }),
  }));
  notifyFrameRegistryChanged();
}

export function isLoopinoFrameMessage(event: MessageEvent, frame: HTMLIFrameElement | null | undefined): boolean {
  const expectedOrigin = frame?.dataset.loopinoFrameOrigin;
  return Boolean(
    frame?.contentWindow
    && expectedOrigin
    && event.source === frame.contentWindow
    && event.origin === expectedOrigin,
  );
}

export function isRegisteredLoopinoFrameMessage(
  event: MessageEvent,
  expectedScope: LoopinoFrameScope,
): boolean {
  return registeredLoopinoFrameOwner(event, expectedScope) !== null;
}

export function registeredLoopinoFrameIdentity(
  event: MessageEvent,
): RegisteredLoopinoFrameIdentity | null {
  for (const [frame, identity] of registeredFrames) {
    if (isLoopinoFrameMessage(event, frame)) return identity;
  }
  return null;
}

export function registeredLoopinoFrameOwner(
  event: MessageEvent,
  expectedScope: LoopinoFrameScope,
): string | null {
  const identity = registeredLoopinoFrameIdentity(event);
  return identity && sameLoopinoFrameScope(identity.scope, expectedScope)
    ? identity.ownerAppId
    : null;
}

export function registeredLoopinoFrameElement(event: MessageEvent, scope: LoopinoFrameScope): HTMLIFrameElement | null {
  for (const [frame, identity] of registeredFrames) {
    if (frame.isConnected && sameLoopinoFrameScope(identity.scope, scope) && isLoopinoFrameMessage(event, frame)) return frame;
  }
  return null;
}

export function isLoopinoFrameInScope(frame: HTMLIFrameElement, scope: LoopinoFrameScope): boolean {
  const identity = registeredFrames.get(frame);
  return Boolean(frame.isConnected && identity && sameLoopinoFrameScope(identity.scope, scope));
}

export function isLoopinoOwnerMessage(
  event: MessageEvent,
  ownerAppId: string,
  expectedScope: LoopinoFrameScope,
): boolean {
  return isValidFrameOwnerId(ownerAppId)
    && (isShellWindowMessage(event)
      || registeredLoopinoFrameOwner(event, expectedScope) === ownerAppId);
}

export function isShellWindowMessage(event: MessageEvent): boolean {
  return event.source === window && event.origin === window.location.origin;
}

export function postToLoopinoFrame(frame: HTMLIFrameElement | null | undefined, message: unknown) {
  if (!frame?.contentWindow) {
    return;
  }
  const targetOrigin = frame.dataset.loopinoFrameOrigin;
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

export function postLoopinoFrameVisibility(
  frame: HTMLIFrameElement | null | undefined,
  payload: {
    app_id?: string;
    owner_app_id?: string;
    visible: boolean;
    widget_id?: string;
  },
) {
  postToLoopinoFrame(frame, {
    type: "loopino.app.visibility-changed",
    ...payload,
  });
}

/** Broadcast only within the current authenticated workspace/session generation. */
export function broadcastLoopinoFrameEvent(scope: LoopinoFrameScope, message: unknown): void {
  for (const [frame, identity] of registeredFrames) {
    if (sameLoopinoFrameScope(identity.scope, scope)) postToLoopinoFrame(frame, message);
  }
}

export function postLoopinoShellTheme(frame: HTMLIFrameElement | null | undefined, theme: ShellThemeState) {
  postToLoopinoFrame(frame, shellThemeMessage(theme));
}

function isValidFrameOwnerId(value: unknown): value is string {
  return typeof value === "string"
    && value.trim() === value
    && value.length > 0
    && value.length <= MAX_FRAME_OWNER_ID_LENGTH
    && !/[\u0000-\u001f\u007f]/u.test(value);
}

export function sameLoopinoFrameScope(
  left: LoopinoFrameScope,
  right: LoopinoFrameScope,
): boolean {
  return left.sessionGeneration === right.sessionGeneration
    && left.workspaceId === right.workspaceId;
}

function isValidFrameScope(value: unknown): value is LoopinoFrameScope {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const scope = value as { sessionGeneration?: unknown; workspaceId?: unknown };
  return isValidFrameScopeId(scope.sessionGeneration) && isValidFrameScopeId(scope.workspaceId);
}

function isValidFrameScopeId(value: unknown): value is string {
  return typeof value === "string"
    && value.trim() === value
    && value.length > 0
    && value.length <= MAX_FRAME_SCOPE_ID_LENGTH
    && !/[\u0000-\u001f\u007f]/u.test(value);
}
