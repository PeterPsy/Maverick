import { nodeIdFromParams } from "./memoryNavigationParams";

type ShellPostTarget = {
  postMessage: (message: unknown, targetOrigin: string) => void;
};

type NotifyOptions = {
  currentWindow?: unknown;
  origin?: string;
  parentWindow?: ShellPostTarget | null;
};

export type ActiveMemorySelectionMessage = {
  owner_app_id?: string;
  selection?: Record<string, unknown>;
  type?: string;
};

export function notifyActiveMemorySelection(nodeId: string, options: NotifyOptions = {}): boolean {
  const normalizedNodeId = nodeId.trim();
  if (!normalizedNodeId) {
    return false;
  }
  const currentWindow = options.currentWindow ?? (typeof window === "undefined" ? null : window);
  const parentWindow = options.parentWindow ?? (typeof window === "undefined" ? null : window.parent);
  if (!parentWindow || parentWindow === currentWindow) {
    return false;
  }
  const origin = options.origin ?? (typeof window === "undefined" ? "*" : window.location.origin);
  parentWindow.postMessage(
    {
      type: "maverick.app.selection-changed",
      owner_app_id: "memory",
      selection: { node_id: normalizedNodeId },
    },
    origin,
  );
  return true;
}

export function nodeIdFromSelectionMessage(message: ActiveMemorySelectionMessage): string {
  if (message.type !== "maverick.app.selection-changed" || message.owner_app_id !== "memory") {
    return "";
  }
  const value = message.selection && typeof message.selection.node_id === "string" ? message.selection.node_id.trim() : "";
  return value;
}

export function nodeIdFromWidgetContext(message: {
  context?: {
    content?: {
      payload?: unknown;
    };
  };
  type?: string;
}): string {
  if (message.type !== "maverick.widget.context-changed") {
    return "";
  }
  const payload = message.context?.content?.payload;
  if (!payload || typeof payload !== "object") {
    return "";
  }
  const activeAppId = scalarString((payload as { active_app_id?: unknown }).active_app_id);
  if (activeAppId !== "memory") {
    return "";
  }
  const activeAppParams = (payload as { active_app_params?: unknown }).active_app_params;
  if (!activeAppParams || typeof activeAppParams !== "object" || Array.isArray(activeAppParams)) {
    return "";
  }
  return nodeIdFromParams(activeAppParams as Record<string, string | boolean | null | undefined>);
}

function scalarString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}
