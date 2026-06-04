import { useEffect, useMemo, useRef, useState } from "react";
import type { ChatProject, ChatThread } from "../../api/client";
import {
  deleteThread,
  listChatProjects,
  markThreadRead,
  updateThread,
} from "../../api/client";
import { useRuntimeThreads } from "../../hooks/useRuntimeThreads";
import { readStoredChatProjects, writeStoredChatProjects } from "../../lib/chatProjectCache";
import { useShellSidebarCloseSwipe } from "../../hooks/useShellSidebarCloseSwipe";
import {
  isMobileLayoutContext,
  isMobileLayoutViewport,
  notifyShell,
  updateFromSidebarPayload,
} from "./chatSidebarStateUtils";
export type { PendingProjectDeletion } from "./chatSidebarStateUtils";
import { buildSections } from "./sections";
import { useSidebarProjectActions } from "./useSidebarProjectActions";
import { useThreadTouchSelection } from "./useThreadTouchSelection";

export function useChatSidebarState() {
  const [projects, setProjects] = useState<ChatProject[]>([]);
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [hasLoadedProjectCatalog, setHasLoadedProjectCatalog] = useState(false);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({});
  const [expandedThreadId, setExpandedThreadId] = useState<string | null>(null);
  const [expandedThreadTitle, setExpandedThreadTitle] = useState("");
  const [isShellMobileLayout, setIsShellMobileLayout] = useState(isMobileLayoutViewport);
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const readReceiptInFlightRef = useRef<Set<string>>(new Set());
  const sections = useMemo(() => buildSections(projects, threads), [projects, threads]);
  function applyProjects(nextProjects: ChatProject[]) {
    setProjects(nextProjects);
    setHasLoadedProjectCatalog(true);
  }

  const projectActions = useSidebarProjectActions({
    activeThreadId,
    projects,
    setActiveThreadId,
    setError,
    setExpandedThreadId,
    setExpandedThreadTitle,
    setIsPending,
    setProjects: applyProjects,
    setThreads,
    threads,
  });

  useShellSidebarCloseSwipe(isShellMobileLayout);
  useRuntimeThreads({
    onSnapshot: (frame) => {
      setWorkspaceId(frame.workspace_id);
      if (!hasLoadedProjectCatalog) {
        const cachedProjects = readStoredChatProjects(frame.workspace_id);
        if (cachedProjects.length) {
          setProjects(cachedProjects);
        }
      }
      setIsInitialLoading(false);
    },
    setError,
    setThreads,
  });

  async function refreshProjects() {
    try {
      const payload = await listChatProjects();
      applyProjects(payload.projects || []);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load chat projects.");
      setIsInitialLoading(false);
    }
  }

  useEffect(() => {
    if (workspaceId && hasLoadedProjectCatalog) {
      writeStoredChatProjects(workspaceId, projects);
    }
  }, [hasLoadedProjectCatalog, projects, workspaceId]);

  useEffect(() => {
    void refreshProjects();
  }, []);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as {
        active_thread_id?: string;
        context?: Record<string, unknown>;
        owner_app_id?: string;
        resource?: string;
        type?: string;
      };
      if (
        (payload.type === "maverick.chat.active-thread-changed" || payload.type === "maverick.widget.data-changed") &&
        payload.owner_app_id === "chat"
      ) {
        if (payload.active_thread_id) {
          setActiveThreadId(payload.active_thread_id);
        }
        if (payload.resource === "projects") {
          void refreshProjects();
        }
      }
      if (payload.type === "maverick.widget.context-changed") {
        setIsShellMobileLayout(isMobileLayoutContext(payload.context));
      }
    }

    window.addEventListener("message", handleShellMessage);
    return () => window.removeEventListener("message", handleShellMessage);
  }, []);

  async function createChat(projectId: string | null = null) {
    setIsPending(true);
    setActiveThreadId(null);
    setExpandedThreadId(null);
    setExpandedThreadTitle("");
    projectActions.clearProjectEditing();
    setError(null);
    notifyShell(undefined, { project_id: projectId });
    setIsPending(false);
  }

  async function moveThread(thread: ChatThread, projectId: string | null) {
    if (thread.project_id === projectId) {
      return;
    }
    try {
      const payload = await updateThread({ thread_id: thread.thread_id, project_id: projectId });
      updateFromSidebarPayload(payload, applyProjects);
      setActiveThreadId(payload.thread.thread_id);
      setExpandedThreadId(null);
      setExpandedThreadTitle("");
      projectActions.clearProjectEditing();
      setError(null);
    } catch (moveError) {
      setError(moveError instanceof Error ? moveError.message : "Unable to move chat.");
    }
  }

  function selectThread(thread: ChatThread) {
    setActiveThreadId(thread.thread_id);
    setExpandedThreadId(null);
    setExpandedThreadTitle("");
    projectActions.cancelProjectDeletion();
    void markThreadReadIfNeeded(thread);
    notifyShell(thread);
  }

  async function markThreadReadIfNeeded(thread: ChatThread) {
    if (!thread.has_unread_completed_response || readReceiptInFlightRef.current.has(thread.thread_id)) {
      return;
    }
    readReceiptInFlightRef.current.add(thread.thread_id);
    setThreads((current) =>
      current.map((item) => (item.thread_id === thread.thread_id ? { ...item, has_unread_completed_response: false } : item)),
    );
    try {
      const payload = await markThreadRead(thread.thread_id);
      setThreads(payload.threads);
      updateFromSidebarPayload(payload, applyProjects);
    } catch {
      // Selection should not be blocked by a best-effort read receipt.
    } finally {
      readReceiptInFlightRef.current.delete(thread.thread_id);
    }
  }

  const { selectThreadFromClick, selectThreadFromPointer, trackThreadTouchStart } = useThreadTouchSelection({
    isShellMobileLayout,
    selectThread,
  });

  async function renameThread(threadId: string, title: string, projectId: string | null) {
    const payload = await updateThread({ thread_id: threadId, title, project_id: projectId });
    updateFromSidebarPayload(payload, applyProjects);
    setActiveThreadId(payload.thread.thread_id);
    setExpandedThreadId(null);
    setExpandedThreadTitle("");
    projectActions.clearProjectEditing();
  }

  async function removeThread(threadId: string) {
    const payload = await deleteThread(threadId);
    updateFromSidebarPayload(payload, applyProjects);
    if (activeThreadId === threadId) {
      setActiveThreadId(null);
    }
    if (expandedThreadId === threadId) {
      setExpandedThreadId(null);
      setExpandedThreadTitle("");
    }
    projectActions.clearProjectEditing();
  }

  function closeExpandedThread() {
    setExpandedThreadId(null);
    setExpandedThreadTitle("");
  }

  function toggleSection(sectionId: string) {
    setCollapsedSections((current) => ({ ...current, [sectionId]: !(current[sectionId] ?? false) }));
  }

  function toggleThreadEdit(thread: ChatThread) {
    projectActions.clearProjectEditing();
    setExpandedThreadId((current) => {
      if (current === thread.thread_id) {
        setExpandedThreadTitle("");
        return null;
      }
      setExpandedThreadTitle(thread.title);
      return thread.thread_id;
    });
  }

  return {
    activeThreadId,
    addProject: projectActions.addProject,
    cancelProjectDeletion: projectActions.cancelProjectDeletion,
    cancelProjectEdit: projectActions.cancelProjectEdit,
    closeExpandedThread,
    collapsedSections,
    confirmProjectDeletion: projectActions.confirmProjectDeletion,
    createChat,
    editingProject: projectActions.editingProject,
    editingProjectRef: projectActions.editingProjectRef,
    error,
    expandedThreadId,
    expandedThreadTitle,
    isInitialLoading,
    isPending,
    isShellMobileLayout,
    moveThread,
    pendingProjectDeletion: projectActions.pendingProjectDeletion,
    projects,
    removeEditingProject: projectActions.removeEditingProject,
    removeThread,
    renameThread,
    saveProjectEdit: projectActions.saveProjectEdit,
    sections,
    selectThreadFromClick,
    selectThreadFromPointer,
    setEditingProjectName: projectActions.setEditingProjectName,
    setExpandedThreadTitle,
    startProjectEdit: projectActions.startProjectEdit,
    toggleSection,
    toggleThreadEdit,
    trackThreadTouchStart,
  };
}
