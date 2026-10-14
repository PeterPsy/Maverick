import type {
  BackendPayload,
  LinkedDocument,
  MartaOpsState,
  Task,
} from "../types";
import type { useRecordPanels } from "../useRecordPanels";
import { openApp } from "../lib/shellNavigation";
import { ContactPanel } from "./ContactPanel";
import { WorkPanel } from "./WorkPanel";
import { TaskPanel } from "./TaskPanel";

export function RecordPanels({
  appId,
  controller,
  state,
  saving,
  mutate,
  integrate,
}: {
  appId: string;
  controller: ReturnType<typeof useRecordPanels>;
  state: MartaOpsState;
  saving: boolean;
  mutate: (body: Record<string, unknown>) => Promise<BackendPayload>;
  integrate: (body: Record<string, unknown>) => Promise<unknown>;
}) {
  const { closePanel, openTask, openWork, newWork } = controller;
  async function toggleTask(task: Task) {
    await mutate({
      action: "update_task",
      id: task.id,
      changes: { done: !task.done },
    });
  }
  return (
    <>
      {controller.panels.map((panel) => {
        if (panel.kind === "contact") {
          const contact =
            state.contacts.find((item) => item.id === panel.id) || null;
          return (
            <ContactPanel
              key={panel.key}
              activity={state.activity}
              contacts={state.contacts}
              item={contact}
              onClose={closePanel}
              onEditTask={openTask}
              onNewTask={() => openTask(null, { contact_id: panel.id || "" })}
              onNewWork={() => newWork(undefined, contact)}
              onNote={async (text) => {
                await mutate({
                  action: "add_note",
                  contact_id: panel.id,
                  text,
                });
              }}
              onSave={async (id, fields) => {
                await mutate(
                  id
                    ? { action: "update_contact", id, changes: fields }
                    : { action: "create_contact", contact: fields },
                );
              }}
              onToggleTask={toggleTask}
              onWork={openWork}
              saving={saving}
              tasks={state.tasks}
              works={state.collaborations}
            />
          );
        }
        if (panel.kind === "work") {
          const work =
            state.collaborations.find((item) => item.id === panel.id) || null;
          return (
            <WorkPanel
              key={panel.key}
              activity={state.activity}
              contacts={state.contacts}
              initialTab={panel.initialTab}
              item={work}
              onClose={closePanel}
              onAddDeliverable={async (id, deliverable) => {
                await mutate({
                  action: "add_deliverable",
                  collaboration_id: id,
                  deliverable,
                });
              }}
              onEditTask={openTask}
              onIntegrate={async (id, target) => {
                await integrate({
                  action:
                    target === "mail"
                      ? "create_mail_draft"
                      : "create_calendar_event",
                  id,
                });
              }}
              integrationOptions={state.integration_options}
              integrationPreferences={state.integration_preferences}
              onRefreshIntegrations={async () => {
                await integrate({ action: "refresh_integrations" });
              }}
              onUpdateIntegrationPreferences={async (changes) => {
                await mutate({
                  action: "update_integration_preferences",
                  changes,
                });
              }}
              onPickDocument={(id) => {
                openApp(state.integration_options.storage_provider_app_id, {
                  picker_mode: "workspace-file",
                  picker_return_app_id: appId,
                  picker_context: id,
                  picker_accept: "any",
                  picker_local_only: true,
                });
              }}
              onUnlinkDocument={async (id, document) => {
                await mutate({
                  action: "unlink_storage_file",
                  id,
                  document_id: document.id,
                });
              }}
              onOpenMail={() => {
                const reference = work?.mail_draft;
                const provider =
                  reference?.provider_app_id ||
                  state.integration_options.mail_provider_app_id;
                if (!provider || !reference?.id) return;
                openApp(provider, {
                  draft: reference.id,
                  connection_id: reference.connection_id || "",
                });
              }}
              onOpenCalendar={() => {
                const reference = work?.calendar_event;
                const provider =
                  reference?.provider_app_id ||
                  state.integration_options.calendar_provider_app_id;
                if (!provider || !reference?.id) return;
                openApp(provider, {
                  event_id: reference.id,
                  app_page: `events/${encodeURIComponent(reference.id)}`,
                });
              }}
              onOpenDocument={(document: LinkedDocument) => {
                const provider =
                  document.provider_app_id ||
                  state.integration_options.storage_provider_app_id;
                if (!provider) return;
                openApp(provider, {
                  workspace_relative_path: document.workspace_relative_path,
                });
              }}
              onNewTask={() =>
                openTask(null, {
                  collaboration_id: panel.id || "",
                  contact_id: work?.contact_id || "",
                  due_date: work?.due_date || "",
                })
              }
              onNote={async (text) => {
                await mutate({
                  action: "add_note",
                  collaboration_id: panel.id,
                  contact_id: work?.contact_id || "",
                  text,
                });
              }}
              onSave={async (id, fields) => {
                await mutate(
                  id
                    ? { action: "update_collaboration", id, changes: fields }
                    : { action: "create_collaboration", collaboration: fields },
                );
              }}
              onToggleTask={toggleTask}
              onUpdateDeliverable={async (id, deliverableId, changes) => {
                await mutate({
                  action: "update_deliverable",
                  collaboration_id: id,
                  id: deliverableId,
                  changes,
                });
              }}
              preset={panel.preset}
              saving={saving}
              tasks={state.tasks}
            />
          );
        }
        const task = state.tasks.find((item) => item.id === panel.id) || null;
        return (
          <TaskPanel
            key={panel.key}
            contacts={state.contacts}
            item={task}
            onClose={closePanel}
            onSave={async (id, fields) => {
              await mutate(
                id
                  ? { action: "update_task", id, changes: fields }
                  : { action: "create_task", task: fields },
              );
            }}
            preset={panel.preset}
            saving={saving}
            works={state.collaborations}
          />
        );
      })}
    </>
  );
}
