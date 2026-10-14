import { useId, useState, type FormEvent } from "react";
import type {
  Activity,
  Collaboration,
  Contact,
  ContactDraft,
  Task,
} from "../types";
import { Drawer } from "./Drawer";
import { Avatar } from "./Avatar";
import { ActivityFeed } from "./ActivityFeed";
import { TaskList } from "./TaskList";
import { WorkRow } from "./WorkRow";

export function ContactPanel({
  item,
  works,
  tasks,
  contacts,
  activity,
  saving,
  onClose,
  onSave,
  onNote,
  onWork,
  onNewWork,
  onNewTask,
  onToggleTask,
  onEditTask,
}: {
  item: Contact | null;
  works: Collaboration[];
  tasks: Task[];
  contacts: Contact[];
  activity: Activity[];
  saving: boolean;
  onClose: () => void;
  onSave: (id: string | null, fields: ContactDraft) => Promise<void>;
  onNote: (text: string) => Promise<void>;
  onWork: (work: Collaboration) => void;
  onNewWork: () => void;
  onNewTask: () => void;
  onToggleTask: (task: Task) => Promise<void>;
  onEditTask: (task: Task) => void;
}) {
  const formId = useId();
  const [tab, setTab] = useState("details");
  const [draft, setDraft] = useState<ContactDraft>(
    () =>
      item || {
        name: "",
        company: "",
        role: "",
        email: "",
        phone: "",
        notes: "",
        tags: [],
        archived: false,
      },
  );
  const [tagText, setTagText] = useState(item?.tags.join(", ") || "");
  const set = <K extends keyof ContactDraft>(key: K, value: ContactDraft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));
  const linkedWorks = works.filter((work) => work.contact_id === item?.id);
  const linkedTasks = tasks.filter((task) => task.contact_id === item?.id);
  const history = activity.filter((entry) => entry.contact_id === item?.id);
  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      await onSave(item?.id || null, {
        ...draft,
        tags: tagText
          .split(",")
          .map((tag) => tag.trim())
          .filter(Boolean),
      });
      onClose();
    } catch {
      /* Retain draft on failure. */
    }
  }
  return (
    <Drawer
      eyebrow={item ? "Scheda contatto" : "Nuovo contatto"}
      title={item?.name || "Una relazione da coltivare"}
      onClose={onClose}
      saving={saving}
      footer={
        <>
          <button
            className="secondary-action"
            disabled={saving}
            onClick={onClose}
            type="button"
          >
            Chiudi
          </button>
          <button
            className="primary-action"
            disabled={saving}
            form={formId}
            hidden={tab !== "details"}
            type="submit"
          >
            {saving ? "Salvo…" : "Salva contatto"}
          </button>
        </>
      }
    >
      {item && (
        <>
          <div className="contact-summary">
            <Avatar name={item.name} />
            <div>
              <strong>{item.company || item.name}</strong>
              <small>
                {item.role || "Referente"}
                {item.archived ? " · Archiviato" : ""}
              </small>
            </div>
          </div>
          <div className="drawer-tabs">
            {[
              ["details", "Dettagli"],
              ["works", `Lavori (${linkedWorks.length})`],
              ["tasks", "Attività"],
              ["history", "Note e cronologia"],
            ].map(([value, label]) => (
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
        </>
      )}
      <form
        className="record-form"
        hidden={tab !== "details"}
        id={formId}
        onSubmit={submit}
      >
        <div className="form-grid">
          <label className="field is-wide">
            <span>Nome</span>
            <input
              autoFocus={!item}
              maxLength={160}
              onChange={(event) => set("name", event.target.value)}
              required
              value={draft.name}
            />
          </label>
          <label className="field">
            <span>Brand / azienda</span>
            <input
              maxLength={160}
              onChange={(event) => set("company", event.target.value)}
              value={draft.company}
            />
          </label>
          <label className="field">
            <span>Ruolo</span>
            <input
              maxLength={160}
              onChange={(event) => set("role", event.target.value)}
              placeholder="Es. Marketing manager"
              value={draft.role}
            />
          </label>
          <label className="field">
            <span>Email</span>
            <input
              maxLength={320}
              onChange={(event) => set("email", event.target.value)}
              type="email"
              value={draft.email}
            />
          </label>
          <label className="field">
            <span>Telefono</span>
            <input
              maxLength={80}
              onChange={(event) => set("phone", event.target.value)}
              type="tel"
              value={draft.phone}
            />
          </label>
          <label className="field is-wide">
            <span>Tag, separati da virgole</span>
            <input
              onChange={(event) => setTagText(event.target.value)}
              placeholder="Outdoor, Agenzia, Sport"
              value={tagText}
            />
          </label>
          <label className="field is-wide">
            <span>Informazioni utili</span>
            <textarea
              maxLength={4000}
              onChange={(event) => set("notes", event.target.value)}
              rows={4}
              value={draft.notes}
            />
          </label>
          {item && (
            <label className="check-field">
              <input
                checked={draft.archived}
                onChange={(event) => set("archived", event.target.checked)}
                type="checkbox"
              />
              Archivia contatto
            </label>
          )}
        </div>
      </form>
      {tab === "works" && (
        <section className="drawer-section">
          <div className="section-heading">
            <h3>Lavori collegati</h3>
            <button
              className="secondary-action"
              onClick={onNewWork}
              type="button"
            >
              Nuovo lavoro
            </button>
          </div>
          {linkedWorks.length ? (
            <div className="row-list drawer-work-list">
              {linkedWorks.map((work) => (
                <WorkRow
                  compact
                  item={work}
                  key={work.id}
                  onOpen={() => onWork(work)}
                />
              ))}
            </div>
          ) : (
            <p className="muted-message">Nessun lavoro collegato.</p>
          )}
        </section>
      )}
      {tab === "tasks" && (
        <section className="drawer-section">
          <div className="section-heading">
            <h3>Attività</h3>
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
              works={works}
            />
          ) : (
            <p className="muted-message">
              Aggiungi un follow-up per questo contatto.
            </p>
          )}
        </section>
      )}
      {tab === "history" && (
        <section className="drawer-section">
          <ActivityFeed entries={history} onNote={onNote} saving={saving} />
        </section>
      )}
    </Drawer>
  );
}
