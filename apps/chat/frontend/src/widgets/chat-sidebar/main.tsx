import { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ChatProject,
  ChatThread,
  createProject,
  createThread,
  deleteProject,
  deleteThread,
  listThreads,
  updateProject,
  updateThread,
} from "../../api/client";
import { FloatingPanel, FloatingPanelPosition, SettingsPanel } from "./SettingsPanel";
import { buildSections, isThreadBusy } from "./sections";
import "./styles.css";

function notifyShell(thread?: ChatThread) {
  window.parent?.postMessage(
    {
      type: "maverick.widget.open-app",
      app_id: "chat",
      params: thread ? { thread_id: thread.thread_id } : { new_chat: true },
    },
    window.location.origin,
  );
}

function updateFromSidebarPayload(
  payload: { projects?: ChatProject[]; threads: ChatThread[] },
  setProjects: (projects: ChatProject[]) => void,
  setThreads: (threads: ChatThread[]) => void,
) {
  setProjects(payload.projects || []);
  setThreads(payload.threads);
}

function panelPositionFromTrigger(trigger: HTMLElement) {
  const triggerRect = trigger.getBoundingClientRect();
  const estimatedPanelHeight = 300;
  const viewportPadding = 8;
  const preferredTop = triggerRect.bottom + 6;
  const maxTop = Math.max(viewportPadding, window.innerHeight - estimatedPanelHeight - viewportPadding);
  return {
    top: Math.min(Math.max(viewportPadding, preferredTop), maxTop),
    right: Math.max(4, window.innerWidth - triggerRect.right),
  };
}

function ChatSidebarWidget() {
  const [projects, setProjects] = useState<ChatProject[]>([]);
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({});
  const [panel, setPanel] = useState<FloatingPanel | null>(null);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sections = useMemo(() => buildSections(projects, threads), [projects, threads]);

  async function refresh() {
    try {
      const payload = await listThreads();
      setProjects(payload.projects || []);
      setThreads(payload.threads || []);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load chats.");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as { owner_app_id?: string; resource?: string; type?: string };
      if (payload.type === "maverick.widget.data-changed" && payload.owner_app_id === "chat") {
        void refresh();
      }
    }

    window.addEventListener("message", handleShellMessage);
    return () => window.removeEventListener("message", handleShellMessage);
  }, []);

  async function createChat(projectId: string | null = null) {
    setIsPending(true);
    try {
      const payload = await createThread("", projectId);
      updateFromSidebarPayload(payload, setProjects, setThreads);
      setActiveThreadId(payload.thread.thread_id);
      setPanel(null);
      setError(null);
      notifyShell(payload.thread);
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "Unable to create chat.");
    } finally {
      setIsPending(false);
    }
  }

  async function moveThread(thread: ChatThread, projectId: string | null) {
    if (thread.project_id === projectId) {
      return;
    }
    try {
      const payload = await updateThread({ thread_id: thread.thread_id, project_id: projectId });
      updateFromSidebarPayload(payload, setProjects, setThreads);
      setActiveThreadId(payload.thread.thread_id);
      setPanel(null);
      setError(null);
    } catch (moveError) {
      setError(moveError instanceof Error ? moveError.message : "Unable to move chat.");
    }
  }

  function selectThread(thread: ChatThread) {
    setActiveThreadId(thread.thread_id);
    notifyShell(thread);
  }

  async function addProject(position?: FloatingPanelPosition) {
    setIsPending(true);
    try {
      const payload = await createProject("New project");
      updateFromSidebarPayload(payload, setProjects, setThreads);
      setPanel(position ? { kind: "project", project: payload.project, position } : null);
      setError(null);
    } catch (projectError) {
      setError(projectError instanceof Error ? projectError.message : "Unable to create project.");
    } finally {
      setIsPending(false);
    }
  }

  async function renameProject(projectId: string, name: string) {
    const payload = await updateProject(projectId, name);
    updateFromSidebarPayload(payload, setProjects, setThreads);
    setPanel(null);
  }

  async function removeProject(projectId: string) {
    const payload = await deleteProject(projectId);
    updateFromSidebarPayload(payload, setProjects, setThreads);
    setPanel(null);
  }

  async function renameThread(threadId: string, title: string, projectId: string | null) {
    const payload = await updateThread({ thread_id: threadId, title, project_id: projectId });
    updateFromSidebarPayload(payload, setProjects, setThreads);
    setActiveThreadId(payload.thread.thread_id);
    setPanel(null);
  }

  async function removeThread(threadId: string) {
    const payload = await deleteThread(threadId);
    updateFromSidebarPayload(payload, setProjects, setThreads);
    if (activeThreadId === threadId) {
      setActiveThreadId(null);
    }
    setPanel(null);
  }

  return (
    <main className="bs-widget-root">
      {error ? <p className="bs-chat-folder__empty">{error}</p> : null}

      <div className="bs-chat-list">
        {sections.map((section) => {
          const isCollapsed = collapsedSections[section.id] ?? false;
          return (
            <section className={`bs-chat-folder ${isCollapsed ? "is-collapsed" : ""}`} key={section.id}>
              <div className="bs-chat-folder__header">
                <p className="bs-chat-folder__title">{section.title}</p>
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
                      aria-label={`Nuova chat in ${section.title}`}
                      className="bs-chat-folder__action-button"
                      onClick={() => createChat(section.projectId)}
                      title="Nuova chat"
                      type="button"
                    >
                      <span aria-hidden="true" className="material-symbols-rounded">add</span>
                    </button>
                  ) : null}
                  {!section.canManage ? (
                    <button
                      aria-label="Nuovo progetto"
                      className="bs-chat-folder__action-button"
                      disabled={isPending}
                      onClick={(event) => addProject(panelPositionFromTrigger(event.currentTarget))}
                      title="Nuovo progetto"
                      type="button"
                    >
                      <span aria-hidden="true" className="material-symbols-rounded">create_new_folder</span>
                    </button>
                  ) : null}
                  {section.canManage ? (
                    <button
                      aria-label={`Azioni per il progetto ${section.title}`}
                      className="bs-instance-menu__trigger bs-folder-menu__trigger"
                      onClick={(event) => {
                        const project = projects.find((item) => item.project_id === section.projectId);
                        if (project) {
                          setPanel({ kind: "project", project, position: panelPositionFromTrigger(event.currentTarget) });
                        }
                      }}
                      type="button"
                    >
                      <span aria-hidden="true" className="material-symbols-rounded">more_horiz</span>
                    </button>
                  ) : null}
                </div>
              </div>
              {!isCollapsed ? (
                <div className="bs-chat-folder__dropzone">
                  {section.items.length ? (
                    section.items.map((thread) => {
                      const isBusy = isThreadBusy(thread);
                      return (
                        <div
                          className={`bs-chat-list__item ${activeThreadId === thread.thread_id ? "is-active" : ""} ${isBusy ? "is-busy" : ""}`}
                          key={thread.thread_id}
                        >
                          <button className="bs-chat-list__select" onClick={() => selectThread(thread)} type="button">
                            <div className="bs-chat-list__row">
                              <div className="bs-chat-list__copy">
                                <p className="bs-chat-list__title" title={thread.title}>{thread.title}</p>
                                <p className="bs-chat-list__subtitle">{thread.runtime_session_id ? "Runtime ready" : "No runtime"}</p>
                              </div>
                              {isBusy ? <span aria-label="Connected and working" className="bs-presence is-busy" title="Connected and working" /> : null}
                            </div>
                          </button>
                          {section.projectId !== thread.project_id ? (
                            <button aria-label={`Sposta ${thread.title} in ${section.title}`} className="bs-instance-menu__trigger" onClick={() => moveThread(thread, section.projectId)} type="button">
                              <span aria-hidden="true" className="material-symbols-rounded">drive_file_move</span>
                            </button>
                          ) : (
                            <button
                              aria-label={`Azioni per ${thread.title}`}
                              className="bs-instance-menu__trigger"
                              onClick={(event) => setPanel({ kind: "thread", thread, position: panelPositionFromTrigger(event.currentTarget) })}
                              type="button"
                            >
                              <span aria-hidden="true" className="material-symbols-rounded">more_horiz</span>
                            </button>
                          )}
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
        })}
      </div>
      {panel ? (
        <SettingsPanel
          onClose={() => setPanel(null)}
          onCreateChat={createChat}
          onDeleteProject={removeProject}
          onDeleteThread={removeThread}
          onRenameProject={renameProject}
          onRenameThread={renameThread}
          panel={panel}
          projects={projects}
        />
      ) : null}
    </main>
  );
}

createRoot(document.getElementById("chat-sidebar-root") as HTMLElement).render(<ChatSidebarWidget />);
