import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import type { ChatThread } from "../../api/client";
import { useRuntimeThreads } from "../../hooks/useRuntimeThreads";
import {
  CHAT_SIDEBAR_SELECTION_CANCEL_DELETE,
  CHAT_SIDEBAR_SELECTION_CONFIRM_DELETE,
  CHAT_SIDEBAR_SELECTION_QUERY,
  CHAT_SIDEBAR_SELECTION_STATE,
  createChatSidebarSelectionChannel,
  isMessageForChatSidebar,
  randomMessageNonce,
  type ChatSidebarSelectionChannel,
} from "../chatSidebarSelectionChannel";
import "./styles.css";

const DEFAULT_APP_ID = "chat";
const PRIMARY_ACTION_LABEL = "New chat";
const DELETE_ACTION_LABEL = "Delete Chat";
const FOOTER_DEFAULT_HEIGHT = "2.65rem";
const FOOTER_CONFIRM_HEIGHT = "5.65rem";
const WIDGET_ID = "chat-sidebar-footer";

function notifyShell(appId: string, projectId: string | null) {
  window.parent?.postMessage(
    {
      type: "maverick.widget.open-app",
      app_id: appId,
      params: {
        new_chat: true,
        new_chat_request_id: crypto.randomUUID(),
        project_id: projectId,
      },
    },
    window.location.origin,
  );
}

function ChatSidebarFooterWidget() {
  const appId = currentChatAppId();
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [workspaceId, setWorkspaceId] = useState("");
  const [selectedThreadCount, setSelectedThreadCount] = useState(0);
  const [isConfirmingDeletion, setIsConfirmingDeletion] = useState(false);
  const [isSelectionDeleting, setIsSelectionDeleting] = useState(false);
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [, setError] = useState<string | null>(null);
  const hasSelectedThreads = selectedThreadCount > 0;
  const primaryActionLabel = hasSelectedThreads ? DELETE_ACTION_LABEL : PRIMARY_ACTION_LABEL;
  const primaryActionAvailable = !isInitialLoading && !isSelectionDeleting && !isConfirmingDeletion;
  const deleteDisabled = isInitialLoading || isSelectionDeleting || selectedThreadCount === 0;
  const channelRef = useRef<ChatSidebarSelectionChannel | null>(null);

  useRuntimeThreads({
    onSnapshot: (frame) => {
      setWorkspaceId(frame.workspace_id);
      setIsInitialLoading(false);
    },
    setError,
    setThreads,
  });

  useEffect(() => {
    postPrimaryActionStateWithLabel(appId, primaryActionAvailable, primaryActionLabel);
  }, [appId, primaryActionAvailable, primaryActionLabel]);

  useEffect(() => {
    const channel = createChatSidebarSelectionChannel((message) => {
      if (!isMessageForChatSidebar(message, appId, workspaceId)) {
        return;
      }
      if (message.type !== CHAT_SIDEBAR_SELECTION_STATE) {
        return;
      }
      setSelectedThreadCount(message.selected_count);
      setIsSelectionDeleting(message.is_deleting);
      if (message.selected_count === 0) {
        setIsConfirmingDeletion(false);
      }
    });
    channelRef.current = channel;
    channel.post({
      app_id: appId,
      type: CHAT_SIDEBAR_SELECTION_QUERY,
      workspace_id: workspaceId || "",
    });
    return () => {
      channel.close();
      if (channelRef.current === channel) {
        channelRef.current = null;
      }
    };
  }, [appId, workspaceId]);

  useEffect(() => {
    postWidgetHeight(appId, isConfirmingDeletion ? FOOTER_CONFIRM_HEIGHT : FOOTER_DEFAULT_HEIGHT);
    return () => postWidgetHeight(appId, FOOTER_DEFAULT_HEIGHT);
  }, [appId, isConfirmingDeletion]);

  useEffect(() => {
    if (!hasSelectedThreads && isConfirmingDeletion) {
      setIsConfirmingDeletion(false);
    }
  }, [hasSelectedThreads, isConfirmingDeletion]);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as {
        active_thread_id?: string;
        owner_app_id?: string;
        type?: string;
        widget_id?: string;
      };
      if (
        payload.owner_app_id === appId &&
        payload.widget_id === WIDGET_ID &&
        payload.type === "maverick.widget.primary-action.query"
      ) {
        postPrimaryActionStateWithLabel(appId, primaryActionAvailable, primaryActionLabel);
        return;
      }
      if (
        payload.owner_app_id === appId &&
        payload.widget_id === WIDGET_ID &&
        payload.type === "maverick.widget.primary-action.invoke"
      ) {
        if (hasSelectedThreads) {
          requestDeleteConfirmation();
          return;
        }
        if (primaryActionAvailable) {
          createChatInCurrentContext();
        }
        return;
      }
      if (
        (payload.type === "maverick.chat.active-thread-changed" || payload.type === "maverick.widget.data-changed") &&
        payload.owner_app_id === appId
      ) {
        setActiveThreadId(payload.active_thread_id || null);
      }
    }

    window.addEventListener("message", handleShellMessage);
    return () => window.removeEventListener("message", handleShellMessage);
  }, [activeThreadId, appId, hasSelectedThreads, primaryActionAvailable, primaryActionLabel, threads]);

  function createChatInCurrentContext() {
    const activeThread = activeThreadId ? threads.find((thread) => thread.thread_id === activeThreadId) : undefined;
    notifyShell(appId, activeThread?.project_id || null);
  }

  function requestDeleteConfirmation() {
    if (deleteDisabled) {
      return;
    }
    setIsConfirmingDeletion(true);
  }

  function cancelDeleteConfirmation() {
    setIsConfirmingDeletion(false);
    channelRef.current?.post({
      app_id: appId,
      request_id: randomMessageNonce(),
      type: CHAT_SIDEBAR_SELECTION_CANCEL_DELETE,
      workspace_id: workspaceId || "",
    });
  }

  function confirmDeleteSelection() {
    if (deleteDisabled) {
      return;
    }
    channelRef.current?.post({
      app_id: appId,
      request_id: randomMessageNonce(),
      type: CHAT_SIDEBAR_SELECTION_CONFIRM_DELETE,
      workspace_id: workspaceId || "",
    });
  }

  function handlePrimaryButtonClick() {
    if (hasSelectedThreads) {
      requestDeleteConfirmation();
      return;
    }
    createChatInCurrentContext();
  }

  return (
    <main className={`bs-chat-sidebar-footer-widget ${isConfirmingDeletion ? "is-confirming-delete" : ""}`}>
      {isConfirmingDeletion ? (
        <div className="bs-chat-sidebar-footer__confirm-actions" role="group" aria-label="Confirm chat deletion">
          <button className="bs-chat-sidebar-footer__confirm-button is-danger" disabled={deleteDisabled} onClick={confirmDeleteSelection} type="button">
            Conferma
          </button>
          <button className="bs-chat-sidebar-footer__confirm-button" disabled={isSelectionDeleting} onClick={cancelDeleteConfirmation} type="button">
            Annulla
          </button>
        </div>
      ) : null}
      <button
        aria-label={hasSelectedThreads ? `Delete ${selectedThreadCount} selected chat${selectedThreadCount === 1 ? "" : "s"}` : "New chat"}
        className={`bs-chat-sidebar-footer__new-chat ${hasSelectedThreads ? "is-delete" : ""}`}
        disabled={hasSelectedThreads ? deleteDisabled : isInitialLoading}
        onClick={handlePrimaryButtonClick}
        type="button"
      >
        {hasSelectedThreads ? <TrashIcon /> : <span aria-hidden="true" className="bs-chat-sidebar-footer__plus" />}
        <span>{primaryActionLabel}</span>
      </button>
    </main>
  );
}

function postPrimaryActionStateWithLabel(appId: string, available: boolean, label: string) {
  window.parent?.postMessage(
    {
      type: "maverick.widget.primary-action.state",
      owner_app_id: appId,
      widget_id: WIDGET_ID,
      available,
      label,
    },
    window.location.origin,
  );
}

function postWidgetHeight(appId: string, height: string) {
  window.parent?.postMessage(
    {
      type: "maverick.widget.resize",
      owner_app_id: appId,
      widget_id: WIDGET_ID,
      height,
    },
    window.location.origin,
  );
}

function TrashIcon() {
  return (
    <svg
      aria-hidden="true"
      className="bs-chat-sidebar-footer__trash"
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.9"
      viewBox="0 0 24 24"
    >
      <path d="M4 7h16M10 11v6M14 11v6M6 7l1 14h10l1-14M9 7V4h6v3" />
    </svg>
  );
}

function currentChatAppId(pathname = typeof window === "undefined" ? "" : window.location.pathname): string {
  return mountedAppIdFromPath(pathname, DEFAULT_APP_ID);
}

function mountedAppIdFromPath(pathname: string, fallback: string): string {
  const match = /^\/api\/apps\/widgets\/([^/?#]+)/.exec(pathname) || /^\/apps\/([^/?#]+)/.exec(pathname);
  if (!match?.[1]) {
    return fallback;
  }
  try {
    return decodeURIComponent(match[1]) || fallback;
  } catch {
    return match[1] || fallback;
  }
}

createRoot(document.getElementById("chat-sidebar-footer-root") as HTMLElement).render(<ChatSidebarFooterWidget />);
