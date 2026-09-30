import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "./Icon";
import { SECTIONS } from "./navigation";
import { IdeasView } from "./components/IdeasView";
import { TodayView } from "./components/TodayView";
import { WorksView } from "./components/WorksView";
import { ContactsView } from "./components/ContactsView";
import { TasksView } from "./components/TasksView";
import {
  isMaverickParentMessage,
  mountedAppIdFromPath,
  openApp,
  postToShell,
  viewFromAppPage,
} from "./lib/shellNavigation";
import type { CollaborationPhase, Task, ViewId } from "./types";
import { useRecordPanels } from "./useRecordPanels";
import { RecordPanels } from "./components/RecordPanels";
import { useMartaOps } from "./useMartaOps";

export function App() {
  const {
    state,
    loading,
    saving,
    error,
    clearError,
    integrate,
    mutate,
    refresh,
  } = useMartaOps();
  const [view, setView] = useState<ViewId>(
    () =>
      viewFromAppPage(
        new URLSearchParams(window.location.search).get("app_page"),
      ) || "today",
  );
  const [query, setQuery] = useState("");
  const controller = useRecordPanels();
  const { openWork, newWork, openContact, openTask } = controller;
  const requests = useRef(new Set<string>());
  const appId = useMemo(() => mountedAppIdFromPath(), []);
  const navigate = useCallback(
    (next: ViewId) => {
      setView(next);
      setQuery("");
      openApp(appId, { app_page: next });
    },
    [appId],
  );
  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (!isMaverickParentMessage(event)) return;
      const message = event.data as {
        app_id?: string;
        params?: Record<string, unknown>;
        type?: string;
      };
      if (
        message.type !== "maverick.app.navigate" ||
        (message.app_id && message.app_id !== appId)
      )
        return;
      const params = message.params || {};
      const next = viewFromAppPage(params.app_page);
      if (next) setView(next);
      for (const [param, target] of [
        ["new_work", "work"],
        ["new_contact", "contacts"],
        ["new_task", "tasks"],
      ] as const) {
        if (params[param] !== true) continue;
        const request = `${param}:${params[`${param}_request_id`] || "initial"}`;
        if (requests.current.has(request)) continue;
        requests.current.add(request);
        setView(target);
        if (param === "new_work") newWork();
        if (param === "new_contact") openContact(null);
        if (param === "new_task") openTask(null);
      }
    }
    window.addEventListener("message", handleMessage);
    postToShell({ type: "maverick.app.ready", app_id: appId });
    return () => window.removeEventListener("message", handleMessage);
  }, [appId, newWork, openContact, openTask]);

  async function toggleTask(task: Task) {
    await mutate({
      action: "update_task",
      id: task.id,
      changes: { done: !task.done },
    });
  }
  async function moveWork(
    id: string,
    phase: CollaborationPhase,
    beforeId: string,
    expectedPhase: CollaborationPhase,
  ) {
    try {
      await mutate({
        action: "move_collaboration",
        id,
        phase,
        before_id: beforeId,
        expected_phase: expectedPhase,
      });
    } catch (error) {
      void refresh();
      throw error;
    }
  }
  function createCurrent() {
    if (view === "contacts") openContact(null);
    else if (view === "tasks") openTask(null);
    else if (view === "ideas")
      document
        .querySelector<HTMLInputElement>('input[aria-label="Titolo idea"]')
        ?.focus();
    else newWork();
  }
  const createLabel =
    view === "contacts"
      ? "Nuovo contatto"
      : view === "tasks"
        ? "Nuova attività"
        : view === "ideas"
          ? "Nuova idea"
          : "Nuovo lavoro";
  const searchLabel =
    view === "contacts"
      ? "Cerca contatti"
      : view === "tasks"
        ? "Cerca attività"
        : view === "ideas"
          ? "Cerca idee"
          : "Cerca lavori";

  return (
    <div className="marta-shell">
      <header className="app-topbar">
        <button
          aria-label="Marta Ops"
          className="brand"
          onClick={() => navigate("today")}
          type="button"
        >
          <span className="brand-mark">
            <Icon name="board" size={18} />
          </span>
          <span>Marta Ops</span>
        </button>
        <nav className="desktop-nav" aria-label="Sezioni">
          {SECTIONS.map(({ id, label, icon }) => (
            <button
              aria-current={view === id ? "page" : undefined}
              className={view === id ? "is-active" : ""}
              key={id}
              onClick={() => navigate(id)}
              type="button"
            >
              <Icon name={icon} size={16} />
              {label}
            </button>
          ))}
        </nav>
        <div className="topbar-actions">
          <label className="app-search">
            <Icon name="search" size={17} />
            <input
              aria-label={searchLabel}
              onChange={(event) => {
                if (view === "today") navigate("work");
                setQuery(event.target.value);
              }}
              placeholder={searchLabel}
              value={query}
            />
          </label>
          <button
            aria-label={createLabel}
            className="primary-action new-work"
            disabled={loading || saving}
            onClick={createCurrent}
            type="button"
          >
            <Icon name="plus" size={17} />
            <span>{createLabel}</span>
          </button>
        </div>
      </header>
      <main className="app-content">
        {loading ? (
          <div className="loading-state">
            <span />
            <p>Carico Marta Ops…</p>
          </div>
        ) : (
          <>
            {view === "today" && (
              <TodayView
                onCreate={() => newWork()}
                onEditTask={(task) => openTask(task)}
                onNewTask={() => openTask(null)}
                onOpen={(work) => openWork(work)}
                onTasks={() => navigate("tasks")}
                onToggleTask={toggleTask}
                onWorks={() => navigate("work")}
                saving={saving}
                state={state}
              />
            )}
            {view === "work" && (
              <WorksView
                items={state.collaborations}
                onCreate={newWork}
                onMove={moveWork}
                onOpen={(work) => openWork(work)}
                query={query}
                saving={saving}
              />
            )}
            {view === "contacts" && (
              <ContactsView
                contacts={state.contacts}
                onCreate={() => openContact(null)}
                onOpen={openContact}
                query={query}
                works={state.collaborations}
              />
            )}
            {view === "tasks" && (
              <TasksView
                contacts={state.contacts}
                onCreate={() => openTask(null)}
                onEdit={(task) => openTask(task)}
                onToggle={toggleTask}
                query={query}
                saving={saving}
                tasks={state.tasks}
                works={state.collaborations}
              />
            )}
            {view === "ideas" && (
              <IdeasView
                ideas={state.ideas}
                onCreate={async (idea) => {
                  await mutate({ action: "create_idea", idea });
                }}
                onUpdate={async (id, changes) => {
                  await mutate({ action: "update_idea", id, changes });
                }}
                query={query}
                saving={saving}
              />
            )}
          </>
        )}
      </main>
      <nav className="mobile-nav" aria-label="Sezioni">
        {SECTIONS.map(({ id, label, icon }) => (
          <button
            aria-current={view === id ? "page" : undefined}
            className={view === id ? "is-active" : ""}
            key={id}
            onClick={() => navigate(id)}
            type="button"
          >
            <Icon name={icon} size={18} />
            <span>{label}</span>
          </button>
        ))}
      </nav>
      <RecordPanels
        controller={controller}
        state={state}
        saving={saving}
        mutate={mutate}
        integrate={integrate}
      />
      {error && (
        <div className="toast" role="alert">
          <span>{error}</span>
          <button
            aria-label="Chiudi messaggio"
            onClick={clearError}
            type="button"
          >
            <Icon name="close" size={16} />
          </button>
        </div>
      )}
    </div>
  );
}
