import { useId, useState, type FormEvent } from "react";
import { todayIso } from "../format";
import type { Collaboration, Contact, Task, TaskDraft } from "../types";
import { Drawer } from "./Drawer";
import { TASK_KINDS } from "./TaskList";

export function TaskPanel({
  item,
  contacts,
  works,
  preset,
  saving,
  onSave,
  onClose,
}: {
  item: Task | null;
  contacts: Contact[];
  works: Collaboration[];
  preset: Partial<TaskDraft>;
  saving: boolean;
  onSave: (id: string | null, fields: TaskDraft) => Promise<void>;
  onClose: () => void;
}) {
  const formId = useId();
  const [draft, setDraft] = useState<TaskDraft>(
    () =>
      item || {
        title: "",
        kind: "task",
        due_date: todayIso(),
        contact_id: "",
        collaboration_id: "",
        done: false,
        notes: "",
        ...preset,
      },
  );
  const set = <K extends keyof TaskDraft>(key: K, value: TaskDraft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));
  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      await onSave(item?.id || null, draft);
      onClose();
    } catch {
      /* Retain entered fields. */
    }
  }
  return (
    <Drawer
      eyebrow={item ? "Modifica attività" : "Nuova attività"}
      onClose={onClose}
      saving={saving}
      title={item?.title || "Il prossimo passo"}
      footer={
        <>
          <button
            className="secondary-action"
            disabled={saving}
            onClick={onClose}
            type="button"
          >
            Annulla
          </button>
          <button
            className="primary-action"
            disabled={saving}
            form={formId}
            type="submit"
          >
            {saving ? "Salvo…" : "Salva attività"}
          </button>
        </>
      }
    >
      <form className="record-form" id={formId} onSubmit={submit}>
        <div className="form-grid">
          <label className="field is-wide">
            <span>Attività</span>
            <input
              autoFocus
              maxLength={240}
              onChange={(event) => set("title", event.target.value)}
              placeholder="Es. Richiamare il referente del brand"
              required
              value={draft.title}
            />
          </label>
          <label className="field">
            <span>Tipo</span>
            <select
              onChange={(event) =>
                set("kind", event.target.value as Task["kind"])
              }
              value={draft.kind}
            >
              {TASK_KINDS.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Scadenza</span>
            <input
              onChange={(event) => set("due_date", event.target.value)}
              type="date"
              value={draft.due_date}
            />
          </label>
          <label className="field is-wide">
            <span>Lavoro collegato</span>
            <select
              onChange={(event) => {
                const id = event.target.value;
                const work = works.find((value) => value.id === id);
                setDraft((current) => ({
                  ...current,
                  collaboration_id: id,
                  contact_id: work?.contact_id || current.contact_id,
                }));
              }}
              value={draft.collaboration_id}
            >
              <option value="">Nessun lavoro</option>
              {works.map((work) => (
                <option key={work.id} value={work.id}>
                  {work.title}
                </option>
              ))}
            </select>
          </label>
          <label className="field is-wide">
            <span>Contatto</span>
            <select
              onChange={(event) => set("contact_id", event.target.value)}
              value={draft.contact_id}
            >
              <option value="">Nessun contatto</option>
              {contacts
                .filter(
                  (contact) =>
                    !contact.archived || contact.id === draft.contact_id,
                )
                .map((contact) => (
                  <option key={contact.id} value={contact.id}>
                    {contact.name}
                    {contact.company ? ` · ${contact.company}` : ""}
                  </option>
                ))}
            </select>
          </label>
          <label className="field is-wide">
            <span>Note</span>
            <textarea
              maxLength={2000}
              onChange={(event) => set("notes", event.target.value)}
              rows={4}
              value={draft.notes}
            />
          </label>
          {item && (
            <label className="check-field">
              <input
                checked={draft.done}
                onChange={(event) => set("done", event.target.checked)}
                type="checkbox"
              />
              Completata
            </label>
          )}
        </div>
      </form>
    </Drawer>
  );
}
