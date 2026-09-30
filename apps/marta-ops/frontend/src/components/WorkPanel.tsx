import { useId, useState, type FormEvent } from "react";
import { Icon } from "../Icon";
import type {
  Activity,
  Collaboration,
  Contact,
  Task,
  WorkDraft,
  WorkPanelTab,
} from "../types";
import { Drawer } from "./Drawer";
import { WorkFields, workDraft } from "./WorkFields";
import { WorkDeliverables } from "./WorkDeliverables";
import { TaskList } from "./TaskList";
import { ActivityFeed } from "./ActivityFeed";

export function WorkPanel({
  item,
  initialTab = "details",
  preset,
  contacts,
  tasks,
  activity,
  saving,
  onClose,
  onSave,
  onIntegrate,
  onAddDeliverable,
  onUpdateDeliverable,
  onNote,
  onNewTask,
  onToggleTask,
  onEditTask,
}: {
  item: Collaboration | null;
  initialTab?: WorkPanelTab;
  preset: Partial<WorkDraft>;
  contacts: Contact[];
  tasks: Task[];
  activity: Activity[];
  saving: boolean;
  onClose: () => void;
  onSave: (
    id: string | null,
    changes: Record<string, unknown>,
  ) => Promise<void>;
  onIntegrate: (id: string, target: "mail" | "calendar") => Promise<void>;
  onAddDeliverable: (
    id: string,
    deliverable: { title: string; due_date: string },
  ) => Promise<void>;
  onUpdateDeliverable: (
    id: string,
    deliverableId: string,
    changes: Record<string, unknown>,
  ) => Promise<void>;
  onNote: (text: string) => Promise<void>;
  onNewTask: () => void;
  onToggleTask: (task: Task) => Promise<void>;
  onEditTask: (task: Task) => void;
}) {
  const formId = useId();
  const [draft, setDraft] = useState(() => workDraft(item, preset));
  const [tab, setTab] = useState<WorkPanelTab>(item ? initialTab : "details");
  const [integrationMessage, setIntegrationMessage] = useState("");
  const [integrationBusy, setIntegrationBusy] = useState<
    "mail" | "calendar" | null
  >(null);
  const linkedTasks = tasks.filter(
    (task) => task.collaboration_id === item?.id,
  );
  const history = activity.filter(
    (entry) => entry.collaboration_id === item?.id,
  );

  function normalizedDraft() {
    const { value_euros, ...fields } = draft;
    const amount = Number(value_euros.replace(",", "."));
    if (
      !Number.isFinite(amount) ||
      amount < 0 ||
      !/^\d*([.,]\d{1,2})?$/.test(value_euros)
    )
      throw new Error("Inserisci un valore economico valido.");
    return { ...fields, value_minor: Math.round(amount * 100) };
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      await onSave(item?.id || null, normalizedDraft());
      onClose();
    } catch (error) {
      if (error instanceof Error) setIntegrationMessage(error.message);
    }
  }
  async function integrate(target: "mail" | "calendar") {
    if (!item) return;
    setIntegrationBusy(target);
    setIntegrationMessage("");
    try {
      await onSave(item.id, normalizedDraft());
      await onIntegrate(item.id, target);
      setIntegrationMessage(
        target === "mail"
          ? "Bozza pronta in Mail."
          : "Scadenza aggiunta al Calendario.",
      );
    } catch (error) {
      if (error instanceof Error) setIntegrationMessage(error.message);
    } finally {
      setIntegrationBusy(null);
    }
  }

  return (
    <Drawer
      eyebrow={item ? "Scheda lavoro" : "Nuovo lavoro"}
      title={item?.title || "La prossima collaborazione"}
      onClose={onClose}
      saving={saving || Boolean(integrationBusy)}
      footer={
        <>
          <button
            className="secondary-action"
            disabled={saving || Boolean(integrationBusy)}
            onClick={onClose}
            type="button"
          >
            Chiudi
          </button>
          <button
            className="primary-action"
            disabled={saving || Boolean(integrationBusy)}
            form={formId}
            hidden={tab !== "details"}
            type="submit"
          >
            {saving ? "Salvo…" : "Salva lavoro"}
          </button>
        </>
      }
    >
      {item && (
        <div className="drawer-tabs">
          {(
            [
              ["details", "Dettagli"],
              ["deliverables", `Consegne (${item.deliverables.length})`],
              ["tasks", "Attività"],
              ["history", "Note e cronologia"],
            ] as Array<[WorkPanelTab, string]>
          ).map(([value, label]) => (
            <button
              aria-pressed={tab === value}
              className={tab === value ? "is-active" : ""}
              key={value}
              onClick={() => setTab(value)}
              type="button"
            >
              {label}
            </button>
          ))}
        </div>
      )}
      <form
        className="record-form"
        hidden={tab !== "details"}
        id={formId}
        onSubmit={submit}
      >
        <WorkFields contacts={contacts} draft={draft} setDraft={setDraft} />
      </form>
      {tab === "details" && item && (
        <section className="integrations-section">
          <div className="section-heading">
            <h3>Azioni collegate</h3>
          </div>
          <div className="integration-actions">
            <button
              className="secondary-action"
              disabled={
                saving ||
                Boolean(integrationBusy) ||
                !(
                  draft.partner_email ||
                  contacts.find((contact) => contact.id === draft.contact_id)
                    ?.email
                )
              }
              onClick={() => void integrate("mail")}
              type="button"
            >
              <Icon name="mail" size={16} />
              {integrationBusy === "mail"
                ? "Creo la bozza…"
                : "Crea bozza Mail"}
            </button>
            <button
              className="secondary-action"
              disabled={saving || Boolean(integrationBusy) || !draft.due_date}
              onClick={() => void integrate("calendar")}
              type="button"
            >
              <Icon name="calendar" size={16} />
              {integrationBusy === "calendar"
                ? "Aggiungo…"
                : "Aggiungi al Calendario"}
            </button>
          </div>
        </section>
      )}
      {integrationMessage && tab === "details" && (
        <p className="inline-feedback" role="status">
          {integrationMessage}
        </p>
      )}
      {item && tab === "deliverables" && (
        <WorkDeliverables
          item={item}
          onAdd={onAddDeliverable}
          onUpdate={onUpdateDeliverable}
          saving={saving}
        />
      )}
      {item && tab === "tasks" && (
        <section className="drawer-section">
          <div className="section-heading">
            <h3>Attività del lavoro</h3>
            <button
              className="secondary-action"
              onClick={onNewTask}
              type="button"
            >
              Nuova attività
            </button>
          </div>
          {linkedTasks.length ? (
            <TaskList
              contacts={contacts}
              onEdit={onEditTask}
              onToggle={onToggleTask}
              saving={saving}
              tasks={linkedTasks}
              works={[item]}
            />
          ) : (
            <p className="muted-message">
              Aggiungi il prossimo passo per questo lavoro.
            </p>
          )}
        </section>
      )}
      {item && tab === "history" && (
        <section className="drawer-section">
          <ActivityFeed entries={history} onNote={onNote} saving={saving} />
        </section>
      )}
    </Drawer>
  );
}
