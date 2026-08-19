import type { ChatProject, ChatThread } from "../../api/client";

export const MOBILE_LAYOUT_QUERY = "(max-width: 979px)";

export type SidebarPayload = {
  projects?: ChatProject[];
};

export type PendingProjectDeletion = {
  message: string;
  projectId: string;
};

export function notifyShell(thread?: ChatThread, params: Record<string, string | boolean | null> = {}) {
  window.parent?.postMessage(
    {
      type: "maverick.widget.open-app",
      app_id: "chat",
      params: thread
        ? { app_page: `threads/${thread.thread_id}` }
        : { new_chat: true, new_chat_request_id: crypto.randomUUID(), ...params },
    },
    window.location.origin,
  );
}

export function updateFromSidebarPayload(payload: SidebarPayload, setProjects: (projects: ChatProject[]) => void) {
  if (Array.isArray(payload.projects)) {
    setProjects(payload.projects);
  }
}

export function isMobileLayoutContext(context: unknown) {
  if (!context || typeof context !== "object") {
    return false;
  }
  const content = (context as { content?: unknown }).content;
  if (!content || typeof content !== "object") {
    return false;
  }
  const payload = (content as { payload?: unknown }).payload;
  return Boolean(payload && typeof payload === "object" && (payload as { is_mobile_layout?: unknown }).is_mobile_layout === true);
}

export function isMobileLayoutViewport() {
  if (typeof window === "undefined") {
    return false;
  }
  try {
    const shellWindow = window.parent && window.parent !== window ? window.parent : window;
    return typeof shellWindow.matchMedia === "function" && shellWindow.matchMedia(MOBILE_LAYOUT_QUERY).matches;
  } catch {
    return typeof window.matchMedia === "function" && window.matchMedia(MOBILE_LAYOUT_QUERY).matches;
  }
}

export function projectDeletionConfirmationMessage(project: ChatProject | undefined, linkedThreadCount: number): string {
  const projectName = project?.name || "this project";
  const chatLabel = linkedThreadCount === 1 ? "1 linked chat" : `${linkedThreadCount} linked chats`;
  return `Delete project "${projectName}" and ${chatLabel}? This action cannot be undone.`;
}
