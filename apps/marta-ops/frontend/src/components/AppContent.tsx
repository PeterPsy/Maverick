import { IdeasView } from "./IdeasView";
import { TodayView } from "./TodayView";
import { WorksView } from "./WorksView";
import { ContactsView } from "./ContactsView";
import { TasksView } from "./TasksView";
import { DeliveriesView } from "./DeliveriesView";
import { AdministrationView } from "./AdministrationView";
import type { CollaborationPhase, Task } from "../types";
import type { useMartaOps } from "../useMartaOps";
import type { useRecordPanels } from "../useRecordPanels";
import type { useAppNavigation } from "../useAppNavigation";

export function AppContent({
  data,
  controller,
  navigation,
}: {
  data: ReturnType<typeof useMartaOps>;
  controller: ReturnType<typeof useRecordPanels>;
  navigation: ReturnType<typeof useAppNavigation>;
}) {
  const { state, loading, saving, mutate, refresh } = data;
  const { openWork, newWork, openContact, openTask } = controller;
  const { view, query, navigate } = navigation;
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
  if (loading)
    return (
      <div className="loading-state">
        <span />
        <p>Carico Marta Ops…</p>
      </div>
    );
  switch (view) {
    case "today":
      return (
        <TodayView
          onCreate={() => newWork()}
          onEditTask={openTask}
          onNewTask={() => openTask(null)}
          onOpen={openWork}
          onTasks={() => navigate("tasks")}
          onToggleTask={toggleTask}
          onWorks={() => navigate("work")}
          saving={saving}
          state={state}
        />
      );
    case "work":
      return (
        <WorksView
          items={state.collaborations}
          onCreate={newWork}
          onMove={moveWork}
          onOpen={openWork}
          query={query}
          saving={saving}
        />
      );
    case "deliveries":
      return (
        <DeliveriesView
          items={state.collaborations}
          onOpen={(work) => openWork(work, {}, "deliverables")}
          onUpdate={async (workId, deliverableId, changes) => {
            await mutate({
              action: "update_deliverable",
              collaboration_id: workId,
              id: deliverableId,
              changes,
            });
          }}
          query={query}
          saving={saving}
        />
      );
    case "contacts":
      return (
        <ContactsView
          contacts={state.contacts}
          onCreate={() => openContact(null)}
          onOpen={openContact}
          query={query}
          works={state.collaborations}
        />
      );
    case "tasks":
      return (
        <TasksView
          contacts={state.contacts}
          onCreate={() => openTask(null)}
          onEdit={openTask}
          onToggle={toggleTask}
          query={query}
          saving={saving}
          tasks={state.tasks}
          works={state.collaborations}
        />
      );
    case "admin":
      return (
        <AdministrationView
          items={state.collaborations}
          onOpen={openWork}
          onUpdate={async (id, changes) => {
            await mutate({ action: "update_collaboration", id, changes });
          }}
          query={query}
          saving={saving}
        />
      );
    case "ideas":
      return (
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
      );
  }
}
