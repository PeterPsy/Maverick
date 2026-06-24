import { useEffect, useMemo, useRef, useState } from "react";
import type { ChatProject, ChatThread } from "../../api/client";
import {
  deleteThread,
  getChatViewFilter,
  listInterAgentRuns,
  listRuntimeSessionEvents,
  listChatProjects,
  markThreadRead,
  setChatViewFilter,
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
import {
  CHAT_SIDEBAR_SELECTION_CONFIRM_DELETE,
  CHAT_SIDEBAR_SELECTION_QUERY,
  CHAT_SIDEBAR_SELECTION_STATE,
  createChatSidebarSelectionChannel,
  isMessageForChatSidebar,
  type ChatSidebarSelectionChannel,
} from "../chatSidebarSelectionChannel";
export type { PendingProjectDeletion } from "./chatSidebarStateUtils";
import { buildSections, filterThreadsBySource, type ThreadSourceFilter } from "./sections";
import {
  buildSearchSections,
  type TranscriptSearchTextByThreadId,
} from "./search";
import {
  indexTranscriptSearchText,
  threadsNeedingTranscriptIndex,
  transcriptSearchSnapshot,
  type TranscriptSearchCacheEntry,
} from "./transcriptSearchIndex";
import { useSidebarProjectActions } from "./useSidebarProjectActions";
import { useThreadTouchSelection } from "./useThreadTouchSelection";

const CHAT_APP_ID = "chat";
const TRANSCRIPT_SEARCH_EVENT_LIMIT = 500;
const TRANSCRIPT_SEARCH_MAX_CONCURRENT = 4;
const THREAD_SOURCE_FILTERS: ThreadSourceFilter[] = ["all", "senses", "multi_agent"];

export function useChatSidebarState() {
  const [projects, setProjects] = useState<ChatProject[]>([]);
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [multiAgentThreadIds, setMultiAgentThreadIds] = useState<Set<string>>(() => new Set());
  const [searchQuery, setSearchQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState<ThreadSourceFilter>("all");
  const [transcriptSearchTextByThreadId, setTranscriptSearchTextByThreadId] = useState<TranscriptSearchTextByThreadId>({});
  const [isTranscriptSearchLoading, setIsTranscriptSearchLoading] = useState(false);
  const [workspaceId, setWorkspaceId] = useState("");
  const [hasLoadedProjectCatalog, setHasLoadedProjectCatalog] = useState(false);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [selectedThreadIds, setSelectedThreadIds] = useState<Set<string>>(() => new Set());
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({});
  const [expandedThreadId, setExpandedThreadId] = useState<string | null>(null);
  const [expandedThreadTitle, setExpandedThreadTitle] = useState("");
  const [isShellMobileLayout, setIsShellMobileLayout] = useState(isMobileLayoutViewport);
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [isPending, setIsPending] = useState(false);
  const [isBulkDeletePending, setIsBulkDeletePending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const readReceiptInFlightRef = useRef<Set<string>>(new Set());
  const transcriptSearchCacheRef = useRef<Map<string, TranscriptSearchCacheEntry>>(new Map());
  const lastPersistedSearchQueryRef = useRef("");
  const [hasLoadedViewFilter, setHasLoadedViewFilter] = useState(false);
  const localSearchRevisionRef = useRef(0);
  const persistedSearchRevisionRef = useRef(0);
  const selectionChannelRef = useRef<ChatSidebarSelectionChannel | null>(null);
  const selectedThreadIdsRef = useRef(selectedThreadIds);
  const threadsRef = useRef(threads);
  const workspaceIdRef = useRef(workspaceId);
  const isBulkDeletePendingRef = useRef(isBulkDeletePending);
  const confirmSelectedThreadDeletionRef = useRef<() => Promise<void>>(async () => {});
  const searchTerm = searchQuery.trim();
  const threadRefreshKey = useMemo(
    () => threads.map((thread) => `${thread.thread_id}:${thread.runtime_session_id}:${thread.updated_at}:${thread.availability}`).sort().join("|"),
    [threads],
  );
  const sourceFilteredThreads = useMemo(
    () => filterThreadsBySource(threads, sourceFilter, multiAgentThreadIds),
    [multiAgentThreadIds, sourceFilter, threads],
  );
  const sourceFilterCounts = useMemo(
    () => ({
      all: threads.length,
      senses: filterThreadsBySource(threads, "senses").length,
      multi_agent: filterThreadsBySource(threads, "multi_agent", multiAgentThreadIds).length,
    }),
    [multiAgentThreadIds, threads],
  );
  const sections = useMemo(
    () =>
      searchTerm
        ? buildSearchSections({
            emptyLabel: isTranscriptSearchLoading ? "Searching messages..." : "No chats found.",
            projects,
            query: searchTerm,
            threads: sourceFilteredThreads,
            transcriptTextByThreadId: transcriptSearchTextByThreadId,
          })
        : buildSections(projects, sourceFilteredThreads),
    [isTranscriptSearchLoading, projects, searchTerm, sourceFilteredThreads, transcriptSearchTextByThreadId],
  );
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

  async function refreshViewFilter() {
    const requestSearchRevision = localSearchRevisionRef.current;
    try {
      const payload = await getChatViewFilter();
      const nextQuery = payload.state?.view_filter?.query || "";
      lastPersistedSearchQueryRef.current = nextQuery;
      setHasLoadedViewFilter(true);
      setSearchQuery((currentQuery) =>
        localSearchRevisionRef.current === requestSearchRevision && localSearchRevisionRef.current === persistedSearchRevisionRef.current
          ? nextQuery
          : currentQuery,
      );
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load chat search.");
    }
  }

  function updateSearchQuery(nextQuery: string) {
    localSearchRevisionRef.current += 1;
    setSearchQuery(nextQuery);
  }

  function updateSourceFilter(nextFilter: ThreadSourceFilter) {
    if (!THREAD_SOURCE_FILTERS.includes(nextFilter)) {
      return;
    }
    setSourceFilter(nextFilter);
  }

  useEffect(() => {
    if (workspaceId && hasLoadedProjectCatalog) {
      writeStoredChatProjects(workspaceId, projects);
    }
  }, [hasLoadedProjectCatalog, projects, workspaceId]);

  useEffect(() => {
    selectedThreadIdsRef.current = selectedThreadIds;
  }, [selectedThreadIds]);

  useEffect(() => {
    threadsRef.current = threads;
    setSelectedThreadIds((current) => {
      const availableThreadIds = new Set(threads.map((thread) => thread.thread_id));
      const next = new Set(Array.from(current).filter((threadId) => availableThreadIds.has(threadId)));
      return next.size === current.size ? current : next;
    });
  }, [threads]);

  useEffect(() => {
    workspaceIdRef.current = workspaceId;
  }, [workspaceId]);

  useEffect(() => {
    isBulkDeletePendingRef.current = isBulkDeletePending;
  }, [isBulkDeletePending]);

  useEffect(() => {
    publishSelectionState();
  }, [isBulkDeletePending, selectedThreadIds, threads, workspaceId]);

  useEffect(() => {
    void refreshProjects();
    void refreshViewFilter();
  }, []);

  useEffect(() => {
    let disposed = false;
    listInterAgentRuns()
      .then((payload) => {
        if (disposed) {
          return;
        }
        setMultiAgentThreadIds(new Set(payload.items.map((item) => item.run.thread_id).filter(Boolean)));
      })
      .catch(() => {
        if (!disposed) {
          setMultiAgentThreadIds(new Set());
        }
      });
    return () => {
      disposed = true;
    };
  }, [threadRefreshKey]);

  useEffect(() => {
    if (!hasLoadedViewFilter) {
      return;
    }
    const nextQuery = searchQuery.trim();
    if (nextQuery === lastPersistedSearchQueryRef.current) {
      return;
    }
    const searchRevision = localSearchRevisionRef.current;
    const timeout = window.setTimeout(() => {
      setChatViewFilter(nextQuery)
        .then(() => {
          lastPersistedSearchQueryRef.current = nextQuery;
          if (localSearchRevisionRef.current === searchRevision) {
            persistedSearchRevisionRef.current = searchRevision;
          }
          setError(null);
        })
        .catch((saveError: Error) => setError(saveError.message));
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [hasLoadedViewFilter, searchQuery]);

  useEffect(() => {
    if (!searchTerm) {
      setIsTranscriptSearchLoading(false);
      setTranscriptSearchTextByThreadId({});
      return;
    }

    const controller = new AbortController();
    let disposed = false;
    const timeout = window.setTimeout(() => {
      const threadsToIndex = threadsNeedingTranscriptIndex(threads, transcriptSearchCacheRef.current);

      if (!threadsToIndex.length) {
        setTranscriptSearchTextByThreadId(transcriptSearchSnapshot(threads, transcriptSearchCacheRef.current));
        setIsTranscriptSearchLoading(false);
        return;
      }

      setIsTranscriptSearchLoading(true);
      indexTranscriptSearchText({
        allThreads: threads,
        cache: transcriptSearchCacheRef.current,
        eventLimit: TRANSCRIPT_SEARCH_EVENT_LIMIT,
        loadEvents: listRuntimeSessionEvents,
        maxConcurrent: TRANSCRIPT_SEARCH_MAX_CONCURRENT,
        onProgress: (snapshot) => {
          if (!disposed) {
            setTranscriptSearchTextByThreadId(snapshot);
          }
        },
        signal: controller.signal,
        threadsToIndex,
      }).then((snapshot) => {
        if (!disposed) {
          setTranscriptSearchTextByThreadId(snapshot);
          setIsTranscriptSearchLoading(false);
        }
      });
    }, 180);

    return () => {
      disposed = true;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [searchTerm, threads]);

  useEffect(() => {
    const channel = createChatSidebarSelectionChannel((message) => {
      if (!isMessageForChatSidebar(message, CHAT_APP_ID, workspaceIdRef.current)) {
        return;
      }
      if (message.type === CHAT_SIDEBAR_SELECTION_QUERY) {
        publishSelectionState();
        return;
      }
      if (message.type === CHAT_SIDEBAR_SELECTION_CONFIRM_DELETE) {
        void confirmSelectedThreadDeletionRef.current();
      }
    });
    selectionChannelRef.current = channel;
    publishSelectionState();
    return () => {
      channel.close();
      if (selectionChannelRef.current === channel) {
        selectionChannelRef.current = null;
      }
    };
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
      if (payload.type === "maverick.widget.data-changed" && payload.owner_app_id === "chat" && payload.resource === "view-state") {
        void refreshViewFilter();
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

  function selectedThreadIdsInCurrentCatalog(): string[] {
    const availableThreadIds = new Set(threadsRef.current.map((thread) => thread.thread_id));
    return Array.from(selectedThreadIdsRef.current).filter((threadId) => availableThreadIds.has(threadId));
  }

  function publishSelectionState() {
    const selectedIds = selectedThreadIdsInCurrentCatalog();
    selectionChannelRef.current?.post({
      app_id: CHAT_APP_ID,
      is_deleting: isBulkDeletePendingRef.current,
      selected_count: selectedIds.length,
      selected_thread_ids: selectedIds,
      type: CHAT_SIDEBAR_SELECTION_STATE,
      workspace_id: workspaceIdRef.current || "",
    });
  }

  function toggleThreadSelection(thread: ChatThread) {
    projectActions.cancelProjectDeletion();
    setSelectedThreadIds((current) => {
      const next = new Set(current);
      if (next.has(thread.thread_id)) {
        next.delete(thread.thread_id);
      } else {
        next.add(thread.thread_id);
      }
      return next;
    });
  }

  function clearDeletedThreadState(deletedThreadIds: Set<string>) {
    if (!deletedThreadIds.size) {
      return;
    }
    setSelectedThreadIds((current) => {
      const next = new Set(current);
      deletedThreadIds.forEach((threadId) => next.delete(threadId));
      return next.size === current.size ? current : next;
    });
    if (activeThreadId && deletedThreadIds.has(activeThreadId)) {
      setActiveThreadId(null);
    }
    if (expandedThreadId && deletedThreadIds.has(expandedThreadId)) {
      setExpandedThreadId(null);
      setExpandedThreadTitle("");
    }
  }

  async function confirmSelectedThreadDeletion() {
    const threadIds = selectedThreadIdsInCurrentCatalog();
    if (!threadIds.length || isBulkDeletePendingRef.current) {
      publishSelectionState();
      return;
    }
    const deletedThreadIds = new Set<string>();
    setIsBulkDeletePending(true);
    setIsPending(true);
    setError(null);
    projectActions.cancelProjectDeletion();
    try {
      for (const threadId of threadIds) {
        const payload = await deleteThread(threadId);
        deletedThreadIds.add(threadId);
        setThreads(payload.threads);
        updateFromSidebarPayload(payload, applyProjects);
      }
      projectActions.clearProjectEditing();
      setError(null);
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Unable to delete selected chats.");
    } finally {
      clearDeletedThreadState(deletedThreadIds);
      setIsBulkDeletePending(false);
      setIsPending(false);
    }
  }

  confirmSelectedThreadDeletionRef.current = confirmSelectedThreadDeletion;

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

  const {
    areThreadActionsRevealed,
    cancelThreadTouch,
    selectThreadFromClick,
    selectThreadFromPointer,
    trackThreadTouchMove,
    trackThreadTouchStart,
  } = useThreadTouchSelection({
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
    setThreads(payload.threads);
    updateFromSidebarPayload(payload, applyProjects);
    clearDeletedThreadState(new Set([threadId]));
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
    areThreadActionsRevealed,
    cancelProjectDeletion: projectActions.cancelProjectDeletion,
    cancelProjectEdit: projectActions.cancelProjectEdit,
    cancelThreadTouch,
    closeExpandedThread,
    collapsedSections,
    confirmProjectDeletion: projectActions.confirmProjectDeletion,
    createChat,
    editingProject: projectActions.editingProject,
    editingProjectRef: projectActions.editingProjectRef,
    error,
    expandedThreadId,
    expandedThreadTitle,
    hasThreadSelection: selectedThreadIds.size > 0,
    isInitialLoading,
    isPending,
    isShellMobileLayout,
    moveThread,
    multiAgentThreadIds,
    pendingProjectDeletion: projectActions.pendingProjectDeletion,
    projects,
    removeEditingProject: projectActions.removeEditingProject,
    removeThread,
    renameThread,
    saveProjectEdit: projectActions.saveProjectEdit,
    sections,
    selectThreadFromClick,
    selectThreadFromPointer,
    selectedThreadIds,
    setEditingProjectName: projectActions.setEditingProjectName,
    setExpandedThreadTitle,
    searchQuery,
    setSearchQuery: updateSearchQuery,
    setSourceFilter: updateSourceFilter,
    startProjectEdit: projectActions.startProjectEdit,
    sourceFilter,
    sourceFilterCounts,
    toggleSection,
    toggleThreadEdit,
    toggleThreadSelection,
    trackThreadTouchMove,
    trackThreadTouchStart,
  };
}
