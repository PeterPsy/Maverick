const MAX_FRAME_CONTEXT_ID_LENGTH = 256;

export type MaverickAppFrameContext = {
  appId: string;
  workspaceId: string;
};

/** Read the immutable app/workspace scope injected by Core into isolated frames. */
export function readMaverickAppFrameContext(): MaverickAppFrameContext | null {
  if (typeof window === "undefined") return null;
  const value = (window as Window & {
    __MAVERICK_APP_FRAME_CONTEXT__?: unknown;
  }).__MAVERICK_APP_FRAME_CONTEXT__;
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const raw = value as { app_id?: unknown; workspace_id?: unknown };
  if (!validContextId(raw.app_id) || !validContextId(raw.workspace_id)) return null;
  return {
    appId: raw.app_id,
    workspaceId: raw.workspace_id,
  };
}

function validContextId(value: unknown): value is string {
  return typeof value === "string"
    && value.trim() === value
    && value.length > 0
    && value.length <= MAX_FRAME_CONTEXT_ID_LENGTH
    && !/[\u0000-\u001f\u007f]/u.test(value);
}
