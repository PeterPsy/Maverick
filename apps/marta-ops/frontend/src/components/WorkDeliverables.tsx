import { useState, type FormEvent } from "react";
import { Icon } from "../Icon";
import { DELIVERABLE_OPTIONS } from "../options";
import type { Collaboration, DeliverableStatus } from "../types";

export function WorkDeliverables({
  item,
  saving,
  onAdd,
  onUpdate,
}: {
  item: Collaboration;
  saving: boolean;
  onAdd: (
    id: string,
    deliverable: { title: string; due_date: string },
  ) => Promise<void>;
  onUpdate: (
    id: string,
    deliverableId: string,
    changes: Record<string, unknown>,
  ) => Promise<void>;
}) {
  const [title, setTitle] = useState("");
  const [dueDate, setDueDate] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    try {
      await onAdd(item.id, { title: title.trim(), due_date: dueDate });
      setTitle("");
      setDueDate("");
    } catch {
      /* Retain input for retry. */
    }
  }
  return (
    <section className="drawer-section">
      <div className="section-heading">
        <h3>Deliverable</h3>
        <span>{item.deliverables.length}</span>
      </div>
      <div className="deliverable-list">
        {item.deliverables.map((deliverable) => (
          <div className="deliverable-row" key={deliverable.id}>
            <button
              aria-label={`${deliverable.status === "published" ? "Riapri" : "Pubblica"} ${deliverable.title}`}
              aria-pressed={deliverable.status === "published"}
              className={`deliverable-check ${deliverable.status === "published" ? "is-done" : ""}`}
              disabled={saving}
              onClick={() =>
                void onUpdate(item.id, deliverable.id, {
                  status:
                    deliverable.status === "published"
                      ? "in_progress"
                      : "published",
                }).catch(() => undefined)
              }
              type="button"
            >
              {deliverable.status === "published" && (
                <Icon name="check" size={14} />
              )}
            </button>
            <div>
              <strong>{deliverable.title}</strong>
              <small>{deliverable.due_date || "Nessuna data"}</small>
            </div>
            <select
              aria-label={`Stato di ${deliverable.title}`}
              disabled={saving}
              onChange={(event) =>
                void onUpdate(item.id, deliverable.id, {
                  status: event.target.value as DeliverableStatus,
                }).catch(() => undefined)
              }
              value={deliverable.status}
            >
              {DELIVERABLE_OPTIONS.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>
      <form className="deliverable-add" onSubmit={submit}>
        <input
          aria-label="Titolo deliverable"
          maxLength={180}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Reel, stories, articolo…"
          required
          value={title}
        />
        <input
          aria-label="Scadenza deliverable"
          onChange={(event) => setDueDate(event.target.value)}
          type="date"
          value={dueDate}
        />
        <button
          className="secondary-action"
          disabled={saving || !title.trim()}
          type="submit"
        >
          Aggiungi
        </button>
      </form>
    </section>
  );
}
