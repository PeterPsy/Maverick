import type { PointerEvent as ReactPointerEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ChatProject,
  ChatThread,
  createProject,
  deleteProject,
  deleteThread,
  listChatProjects,
  updateProject,
  updateThread,
} from "../../api/client";
import { useRuntimeThreads } from "../../hooks/useRuntimeThreads";
import { useShellSidebarCloseSwipe } from "../../hooks/useShellSidebarSwipe";
import { buildSections, isThreadBusy } from "./sections";
import { ThreadInlineActions } from "./ThreadInlineActions";
import "./styles.css";

const MOBILE_LAYOUT_QUERY = "(max-width: 979px)";

function notifyShell(thread?: ChatThread, params: Record<string, string | boolean | null> = {}) {
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

function updateFromSidebarPayload(payload: { projects?: ChatProject[] }, setProjects: (projects: ChatProject[]) => void) {
  setProjects(payload.projects || []);
}

function isMobileLayoutContext(context: unknown) {
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

function isMobileLayoutViewport() {
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

function ChatSidebarWidget() {
  const [projects, setProjects] = useState<ChatProject[]>([]);
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({});
  const [expandedThreadId, setExpandedThreadId] = useState<string | null>(null);
  const [expandedThreadTitle, setExpandedThreadTitle] = useState("");
  const [editingProject, setEditingProject] = useState<{ projectId: string; name: string } | null>(null);
  const [deletingProjectId, setDeletingProjectId] = useState<string | null>(null);
  const [projectDeleteProgress, setProjectDeleteProgress] = useState<{ deleted: number; total: number } | null>(null);
  const [isShellMobileLayout, setIsShellMobileLayout] = useState(isMobileLayoutViewport);
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const editingProjectRef = useRef<HTMLElement | null>(null);
  const touchThreadPointerStartRef = useRef<{ threadId: string; x: number; y: number } | null>(null);
  const touchSelectedThreadIdRef = useRef<string | null>(null);
  const touchSelectedThreadResetRef = useRef<number | null>(null);
  const sections = useMemo(() => buildSections(projects, threads), [projects, threads]);

  useShellSidebarCloseSwipe(isShellMobileLayout);
  useRuntimeThreads({ onSnapshot: () => setIsInitialLoading(false), setError, setThreads });

  async function refreshProjects() {
    try {
      const payload = await listChatProjects();
      setProjects(payload.projects || []);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load chat projects.");
      setIsInitialLoading(false);
    }
  }

  useEffect(() => {
    void refreshProjects();
    return () => {
      if (touchSelectedThreadResetRef.current !== null) {
        window.clearTimeout(touchSelectedThreadResetRef.current);
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
    }

    window.addEventListener("message", handleShellMessage);
    return () => window.removeEventListener("message", handleShellMessage);
  }, []);

  useEffect(() => {
    if (!editingProject) {
      return;
    }
    function cancelProjectEditFromOutside(event: PointerEvent) {
      const target = event.target;
      if (target instanceof Node && editingProjectRef.current?.contains(target)) {
        return;
      }
      setEditingProject(null);
    }
    document.addEventListener("pointerdown", cancelProjectEditFromOutside);
    return () => document.removeEventListener("pointerdown", cancelProjectEditFromOutside);
  }, [editingProject?.projectId]);

  async function createChat(projectId: string | null = null) {
    setIsPending(true);
    setActiveThreadId(null);
    setExpandedThreadId(null);
    setExpandedThreadTitle("");
    setEditingProject(null);
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
      updateFromSidebarPayload(payload, setProjects);
      setActiveThreadId(payload.thread.thread_id);
      setExpandedThreadId(null);
      setExpandedThreadTitle("");
      setEditingProject(null);
      setError(null);
    } catch (moveError) {
      setError(moveError instanceof Error ? moveError.message : "Unable to move chat.");
    }
  }

  function selectThread(thread: ChatThread) {
    setActiveThreadId(thread.thread_id);
    setExpandedThreadId(null);
    setExpandedThreadTitle("");
    notifyShell(thread);
  }

  function markTouchThreadSelection(threadId: string) {
    touchSelectedThreadIdRef.current = threadId;
    if (touchSelectedThreadResetRef.current !== null) {
      window.clearTimeout(touchSelectedThreadResetRef.current);
    }
    touchSelectedThreadResetRef.current = window.setTimeout(() => {
      touchSelectedThreadIdRef.current = null;
      touchSelectedThreadResetRef.current = null;
    }, 450);
  }

  function trackThreadTouchStart(event: ReactPointerEvent<HTMLButtonElement>, thread: ChatThread) {
    if (!isShellMobileLayout || event.pointerType !== "touch") {
      return;
    }
    touchThreadPointerStartRef.current = { threadId: thread.thread_id, x: event.clientX, y: event.clientY };
  }

  function selectThreadFromPointer(event: ReactPointerEvent<HTMLButtonElement>, thread: ChatThread) {
    if (!isShellMobileLayout || event.pointerType !== "touch") {
      return;
    }
    const start = touchThreadPointerStartRef.current;
    touchThreadPointerStartRef.current = null;
    if (start?.threadId === thread.thread_id) {
      const movedX = Math.abs(event.clientX - start.x);
      const movedY = Math.abs(event.clientY - start.y);
      if (movedX > 10 || movedY > 10) {
        return;
      }
    }
    event.preventDefault();
    event.stopPropagation();
    markTouchThreadSelection(thread.thread_id);
    selectThread(thread);
  }

  function selectThreadFromClick(thread: ChatThread) {
    if (touchSelectedThreadIdRef.current === thread.thread_id) {
      touchSelectedThreadIdRef.current = null;
      if (touchSelectedThreadResetRef.current !== null) {
        window.clearTimeout(touchSelectedThreadResetRef.current);
        touchSelectedThreadResetRef.current = null;
      }
      return;
    }
    selectThread(thread);
  }

  async function addProject() {
    setIsPending(true);
    try {
      const payload = await createProject("New project");
      updateFromSidebarPayload(payload, setProjects);
      setEditingProject(null);
      setError(null);
    } catch (projectError) {
      setError(projectError instanceof Error ? projectError.message : "Unable to create project.");
    } finally {
      setIsPending(false);
    }
  }

  async function renameProject(projectId: string, name: string) {
    const payload = await updateProject(projectId, name);
    updateFromSidebarPayload(payload, setProjects);
    setExpandedThreadId(null);
    setExpandedThreadTitle("");
    setEditingProject(null);
  }

  async function removeProject(projectId: string) {
    const payload = await deleteProject(projectId);
    updateFromSidebarPayload(payload, setProjects);
    setEditingProject(null);
  }

  async function renameThread(threadId: string, title: string, projectId: string | null) {
    const payload = await updateThread({ thread_id: threadId, title, project_id: projectId });
    updateFromSidebarPayload(payload, setProjects);
    setActiveThreadId(payload.thread.thread_id);
    setExpandedThreadId(null);
    setExpandedThreadTitle("");
    setEditingProject(null);
  }

  async function removeThread(threadId: string) {
    const payload = await deleteThread(threadId);
    updateFromSidebarPayload(payload, setProjects);
    if (activeThreadId === threadId) {
      setActiveThreadId(null);
    }
    if (expandedThreadId === threadId) {
      setExpandedThreadId(null);
      setExpandedThreadTitle("");
    }
    setEditingProject(null);
  }

  async function deleteProjectThreads(projectId: string, projectThreads: ChatThread[]) {
    if (!projectThreads.length || deletingProjectId) {
      return;
    }
    setDeletingProjectId(projectId);
    setProjectDeleteProgress({ deleted: 0, total: projectThreads.length });
    setExpandedThreadId(null);
    setExpandedThreadTitle("");
    setEditingProject(null);
    setError(null);
    try {
      for (const [index, thread] of projectThreads.entries()) {
        const payload = await deleteThread(thread.thread_id);
        updateFromSidebarPayload(payload, setProjects);
        setThreads(payload.threads || []);
        setActiveThreadId((current) => (current === thread.thread_id ? null : current));
        setProjectDeleteProgress({ deleted: index + 1, total: projectThreads.length });
      }
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Unable to delete project chats.");
    } finally {
      setDeletingProjectId(null);
      setProjectDeleteProgress(null);
    }
  }

  function startProjectEdit(project: ChatProject) {
    setExpandedThreadId(null);
    setExpandedThreadTitle("");
    setEditingProject({ projectId: project.project_id, name: project.name });
    setError(null);
  }

  function cancelProjectEdit() {
    setEditingProject(null);
  }

  async function saveProjectEdit() {
    if (!editingProject) {
      return;
    }
    const nextName = editingProject.name.trim();
    if (!nextName) {
      setError("Project name cannot be empty.");
      return;
    }
    const project = projects.find((item) => item.project_id === editingProject.projectId);
    if (project?.name === nextName) {
      setEditingProject(null);
      return;
    }
    setIsPending(true);
    try {
      await renameProject(editingProject.projectId, nextName);
      setError(null);
    } catch (projectError) {
      setError(projectError instanceof Error ? projectError.message : "Unable to save project.");
    } finally {
      setIsPending(false);
    }
  }

  async function removeEditingProject(projectId: string) {
    setIsPending(true);
    try {
      await removeProject(projectId);
      setError(null);
    } catch (projectError) {
      setError(projectError instanceof Error ? projectError.message : "Unable to delete project.");
    } finally {
      setIsPending(false);
    }
  }

  function closeExpandedThread() {
    setExpandedThreadId(null);
    setExpandedThreadTitle("");
  }

  return (
    <main className={`bs-widget-root ${isShellMobileLayout ? "is-shell-mobile" : ""}`}>
      {error ? <p className="bs-chat-folder__empty">{error}</p> : null}

      <div className="bs-chat-list">
        {isInitialLoading ? (
          <ChatSidebarSkeleton />
        ) : (
          sections.map((section) => {
            const isCollapsed = collapsedSections[section.id] ?? false;
            const isEditingProject = editingProject?.projectId === section.projectId;
            const isDeletingProject = deletingProjectId === section.projectId;
            const isDeletingAnyProject = deletingProjectId !== null;
            const deleteProgress = isDeletingProject ? projectDeleteProgress : null;
            const editingName = isEditingProject ? editingProject.name : section.title;
            return (
              <section className={`bs-chat-folder ${isCollapsed ? "is-collapsed" : ""} ${isEditingProject ? "is-project-editing" : ""}`} key={section.id}>
                <div
                  className="bs-chat-folder__header"
                  ref={(element) => {
                    if (isEditingProject) {
                      editingProjectRef.current = element;
                    }
                  }}
                >
                  {isEditingProject ? (
                    <span className="bs-chat-folder__title-input-frame">
                      <input
                        aria-label={`Rinomina progetto ${section.title}`}
                        autoFocus
                        className="bs-chat-folder__title-input"
                        onChange={(event) => setEditingProject({ projectId: editingProject.projectId, name: event.target.value })}
                        onKeyDown={(event) => {
                          if (event.key === "Escape") {
                            event.preventDefault();
                            cancelProjectEdit();
                          }
                          if (event.key === "Enter") {
                            event.preventDefault();
                            void saveProjectEdit();
                          }
                        }}
                        value={editingName}
                      />
                    </span>
                  ) : (
                    <p className="bs-chat-folder__title">{section.title}</p>
                  )}
                  <div className="bs-chat-folder__header-actions">
                    <button
                      aria-expanded={!isCollapsed}
                      aria-label={`${isCollapsed ? "Mostra" : "Nascondi"} chat del progetto ${section.title}`}
                      className={`bs-chat-folder__toggle ${isCollapsed ? "is-collapsed" : ""}`}
                      onClick={() => setCollapsedSections((current) => ({ ...current, [section.id]: !(current[section.id] ?? false) }))}
                      type="button"
                    >
                      <span className="bs-chat-folder__count">{section.items.length}</span>
                      <span aria-hidden="true" className="material-symbols-rounded bs-chat-folder__chevron">expand_more</span>
                    </button>
                    {section.canManage ? (
                      <button
                        aria-label={isEditingProject ? `Elimina progetto ${section.title}` : `Nuova chat in ${section.title}`}
                        className={`bs-chat-folder__action-button ${isEditingProject ? "is-danger" : ""}`}
                        disabled={isPending || isDeletingAnyProject}
                        onClick={() => {
                          if (isEditingProject && section.projectId) {
                            void removeEditingProject(section.projectId);
                            return;
                          }
                          void createChat(section.projectId);
                        }}
                        title={isEditingProject ? "Elimina progetto" : "Nuova chat"}
                        type="button"
                      >
                        <span aria-hidden="true" className="material-symbols-rounded">{isEditingProject ? "delete" : "add"}</span>
                      </button>
                    ) : null}
                    {section.canManage && !isEditingProject ? (
                      <button
                        aria-label={`Elimina tutte le chat in ${section.title}`}
                        className="bs-chat-folder__action-button is-danger"
                        disabled={isPending || isDeletingAnyProject || section.items.length === 0}
                        onClick={() => {
                          if (section.projectId) {
                            void deleteProjectThreads(section.projectId, section.items);
                          }
                        }}
                        title="Elimina chat del progetto"
                        type="button"
                      >
                        <span aria-hidden="true" className="material-symbols-rounded">delete_sweep</span>
                      </button>
                    ) : null}
                    {!section.canManage ? (
                      <button
                        aria-label="Nuovo progetto"
                        className="bs-chat-folder__action-button"
                        disabled={isPending || isDeletingAnyProject}
                        onClick={() => addProject()}
                        title="Nuovo progetto"
                        type="button"
                      >
                        <span aria-hidden="true" className="material-symbols-rounded">create_new_folder</span>
                      </button>
                    ) : null}
                    {section.canManage ? (
                      <button
                        aria-label={isEditingProject ? `Salva modifiche a ${section.title}` : `Modifica progetto ${section.title}`}
                        className="bs-instance-menu__trigger bs-folder-menu__trigger"
                        disabled={isPending || isDeletingAnyProject || (isEditingProject && !editingName.trim())}
                        onClick={() => {
                          const project = projects.find((item) => item.project_id === section.projectId);
                          if (!project) {
                            return;
                          }
                          if (isEditingProject) {
                            void saveProjectEdit();
                            return;
                          }
                          startProjectEdit(project);
                        }}
                        title={isEditingProject ? "Salva" : "Modifica progetto"}
                        type="button"
                      >
                        <span aria-hidden="true" className="material-symbols-rounded">{isEditingProject ? "check" : "more_horiz"}</span>
                      </button>
                    ) : null}
                  </div>
                </div>
                {deleteProgress ? (
                  <div className="bs-chat-folder__delete-progress" role="status" aria-live="polite">
                    <div className="bs-chat-folder__delete-progress-copy">
                      <span>Eliminazione chat</span>
                      <strong>{deleteProgress.deleted}/{deleteProgress.total}</strong>
                    </div>
                    <div className="bs-chat-folder__delete-progress-track">
                      <span
                        className="bs-chat-folder__delete-progress-bar"
                        style={{ width: `${Math.round((deleteProgress.deleted / Math.max(1, deleteProgress.total)) * 100)}%` }}
                      />
                    </div>
                  </div>
                ) : null}
                {!isCollapsed ? (
                  <div className="bs-chat-folder__dropzone">
                    {section.items.length ? (
                      section.items.map((thread) => {
                        const isBusy = isThreadBusy(thread);
                        const isExpanded = expandedThreadId === thread.thread_id;
                        return (
                          <div
                            className={`bs-chat-list__item ${activeThreadId === thread.thread_id ? "is-active" : ""} ${isBusy ? "is-busy" : ""} ${isExpanded ? "is-expanded" : ""}`}
                            key={thread.thread_id}
                          >
                            {isBusy ? <BusyChatGlow /> : null}
                            <div className="bs-chat-list__select">
                              {isExpanded ? (
                                <span className="bs-chat-list__title-input-frame">
                                  <input
                                    aria-label={`Modifica titolo ${thread.title}`}
                                    autoFocus
                                    className="bs-chat-list__title-input"
                                    onChange={(event) => setExpandedThreadTitle(event.target.value)}
                                    onKeyDown={(event) => {
                                      if (event.key === "Escape") {
                                        event.preventDefault();
                                        closeExpandedThread();
                                      }
                                    }}
                                    value={expandedThreadTitle}
                                  />
                                </span>
                              ) : (
                                <button
                                  className="bs-chat-list__select-button"
                                  onClick={() => selectThreadFromClick(thread)}
                                  onPointerDown={(event) => trackThreadTouchStart(event, thread)}
                                  onPointerUp={(event) => selectThreadFromPointer(event, thread)}
                                  type="button"
                                >
                                  <div className="bs-chat-list__row">
                                    <div className="bs-chat-list__copy">
                                      <p className="bs-chat-list__title" title={thread.title}>{thread.title}</p>
                                    </div>
                                  </div>
                                </button>
                              )}
                            </div>
                            {section.projectId !== thread.project_id ? (
                              <button aria-label={`Sposta ${thread.title} in ${section.title}`} className="bs-instance-menu__trigger" onClick={() => moveThread(thread, section.projectId)} type="button">
                                <span aria-hidden="true" className="material-symbols-rounded">drive_file_move</span>
                              </button>
                            ) : (
                              <button
                                aria-expanded={isExpanded}
                                aria-label={`Modifica ${thread.title}`}
                                className="bs-instance-menu__trigger"
                                onClick={() => {
                                  setEditingProject(null);
                                  setExpandedThreadId((current) => {
                                    if (current === thread.thread_id) {
                                      setExpandedThreadTitle("");
                                      return null;
                                    }
                                    setExpandedThreadTitle(thread.title);
                                    return thread.thread_id;
                                  });
                                }}
                                type="button"
                              >
                                <span aria-hidden="true" className="material-symbols-rounded">more_horiz</span>
                              </button>
                            )}
                            {isExpanded ? (
                              <ThreadInlineActions
                                onClose={closeExpandedThread}
                                onDeleteThread={removeThread}
                                onRenameThread={renameThread}
                                projects={projects}
                                title={expandedThreadTitle}
                                thread={thread}
                              />
                            ) : null}
                          </div>
                        );
                      })
                    ) : (
                      <p className="bs-chat-folder__empty">Nessuna chat in questo progetto.</p>
                    )}
                  </div>
                ) : null}
              </section>
            );
          })
        )}
      </div>
    </main>
  );
}

function ChatSidebarSkeleton() {
  return (
    <div aria-hidden="true" className="bs-chat-sidebar-skeleton">
      {Array.from({ length: 3 }).map((_, sectionIndex) => (
        <section className="bs-chat-sidebar-skeleton__section" key={sectionIndex}>
          <div className="bs-chat-sidebar-skeleton__header">
            <span className="bs-chat-sidebar-skeleton__line bs-chat-sidebar-skeleton__line--title" />
            <span className="bs-chat-sidebar-skeleton__chip" />
          </div>
          {Array.from({ length: sectionIndex === 0 ? 4 : 3 }).map((_, rowIndex) => (
            <div className="bs-chat-sidebar-skeleton__row" key={rowIndex}>
              <span className="bs-chat-sidebar-skeleton__line bs-chat-sidebar-skeleton__line--row" />
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}

function BusyChatGlow() {
  return (
    <span aria-hidden="true" className="bs-chat-list__glow">
      <span className="bs-chat-list__glow-layer bs-chat-list__glow-layer--outer" />
      <span className="bs-chat-list__glow-layer bs-chat-list__glow-layer--a" />
      <span className="bs-chat-list__glow-layer bs-chat-list__glow-layer--b" />
      <span className="bs-chat-list__glow-layer bs-chat-list__glow-layer--c" />
      <span className="bs-chat-list__glow-layer bs-chat-list__glow-layer--bright" />
      <span className="bs-chat-list__glow-layer bs-chat-list__glow-layer--rim" />
    </span>
  );
}

createRoot(document.getElementById("chat-sidebar-root") as HTMLElement).render(<ChatSidebarWidget />);
