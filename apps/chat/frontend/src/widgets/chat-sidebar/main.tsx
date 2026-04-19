import { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { ChatProject, ChatThread, createThread, listThreads, updateThread } from "../../api/client";
import "./styles.css";

type FolderSection = {
  id: string;
  projectId: string | null;
  title: string;
  items: ChatThread[];
  canManage: boolean;
};

function buildSections(projects: ChatProject[], threads: ChatThread[]): FolderSection[] {
  const sections: FolderSection[] = projects
    .slice()
    .sort((left, right) => left.name.localeCompare(right.name, "it", { sensitivity: "base" }))
    .map((project) => ({
      id: project.project_id,
      projectId: project.project_id,
      title: project.name,
      canManage: true,
      items: threads.filter((thread) => thread.project_id === project.project_id),
    }));
  const projectIds = new Set(projects.map((project) => project.project_id));
  const unassigned = threads.filter((thread) => !thread.project_id || !projectIds.has(thread.project_id));
  if (unassigned.length || !sections.length) {
    sections.unshift({
      id: "unassigned",
      projectId: null,
      title: "Senza progetto",
      canManage: false,
      items: unassigned,
    });
  }
  return sections;
}

function isThreadBusy(thread: ChatThread): boolean {
  return thread.availability === "busy";
}

function notifyShell(thread?: ChatThread) {
  window.parent?.postMessage(
    {
      type: "maverick.widget.open-app",
      app_id: "chat",
      thread_id: thread?.thread_id || null,
    },
    window.location.origin,
  );
}

function ChatSidebarWidget() {
  const [projects, setProjects] = useState<ChatProject[]>([]);
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({});
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

  async function createChat(projectId: string | null = null) {
    setIsPending(true);
    try {
      const payload = await createThread("", projectId);
      setProjects(payload.projects || projects);
      setThreads(payload.threads);
      setActiveThreadId(payload.thread.thread_id);
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
      setProjects(payload.projects || projects);
      setThreads(payload.threads);
      setActiveThreadId(payload.thread.thread_id);
      setError(null);
    } catch (moveError) {
      setError(moveError instanceof Error ? moveError.message : "Unable to move chat.");
    }
  }

  function selectThread(thread: ChatThread) {
    setActiveThreadId(thread.thread_id);
    notifyShell(thread);
  }

  return (
    <main className="bs-widget-root">
      <button
        className="bs-sidebar__nav-button"
        disabled={isPending}
        onClick={() => createChat()}
        title="Crea una nuova chat"
        type="button"
      >
        <span className="bs-sidebar__nav-leading">
          <span className="bs-sidebar__nav-icon">
            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none">
              <path d="M7.75 8.25h8.5M7.75 12h5.5M10 18.25l-3.2 2.5v-2.5H6A2.25 2.25 0 0 1 3.75 16V8A2.25 2.25 0 0 1 6 5.75h12A2.25 2.25 0 0 1 20.25 8v8A2.25 2.25 0 0 1 18 18.25H10Z" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.6" />
              <path d="M17.75 4.75v4.5M15.5 7h4.5" stroke="currentColor" strokeLinecap="round" strokeWidth="1.6" />
            </svg>
          </span>
          <span className="bs-sidebar__nav-copy">
            <span className="bs-sidebar__nav-title">New chat</span>
          </span>
        </span>
      </button>

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
                    <span aria-hidden="true" className="bs-chat-folder__chevron">⌄</span>
                  </button>
                  {section.canManage ? (
                    <button
                      aria-label={`Nuova chat in ${section.title}`}
                      className="bs-chat-folder__action-button"
                      onClick={() => createChat(section.projectId)}
                      title="Nuova chat"
                      type="button"
                    >
                      <svg aria-hidden="true" viewBox="0 0 24 24" fill="none">
                        <path d="M12 5.75v12.5M5.75 12h12.5" stroke="currentColor" strokeLinecap="round" strokeWidth="1.7" />
                      </svg>
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
                            <button className="bs-instance-menu__trigger" onClick={() => moveThread(thread, section.projectId)} type="button">⋯</button>
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
        })}
      </div>
    </main>
  );
}

createRoot(document.getElementById("chat-sidebar-root") as HTMLElement).render(<ChatSidebarWidget />);
