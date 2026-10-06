import { useViewState } from "../lib/viewState";
import { daysFromToday } from "../format";
import type { Collaboration, Contact, Task } from "../types";
import { TaskList } from "./TaskList";

export function TasksView({
  tasks,
  works,
  contacts,
  query,
  saving,
  onCreate,
  onToggle,
  onEdit,
}: {
  tasks: Task[];
  works: Collaboration[];
  contacts: Contact[];
  query: string;
  saving: boolean;
  onCreate: () => void;
  onToggle: (task: Task) => Promise<void>;
  onEdit: (task: Task) => void;
}) {
  const [filter, setFilter] = useViewState("tasks.filter", "open");
  const [contactId, setContactId] = useViewState("tasks.contactId", "");
  const needle = query.trim().toLocaleLowerCase("it");
  const visible = tasks
    .filter(
      (task) =>
        (filter === "done"
          ? task.done
          : !task.done &&
            (filter !== "today" || daysFromToday(task.due_date) <= 0)) &&
        (!contactId || task.contact_id === contactId) &&
        (!needle ||
          [
            task.title,
            task.notes,
            contacts.find((contact) => contact.id === task.contact_id)?.name,
            works.find((work) => work.id === task.collaboration_id)?.title,
          ]
            .join(" ")
            .toLocaleLowerCase("it")
            .includes(needle)),
    )
    .sort((a, b) => (a.due_date || "9999").localeCompare(b.due_date || "9999"));
  return (
    <section className="page tasks-page">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Follow-up e promemoria</p>
          <h1>
            Attività <span className="heading-count">{visible.length}</span>
          </h1>
        </div>
        <button className="secondary-action" onClick={onCreate} type="button">
          Nuova attività
        </button>
      </header>
      <div className="view-toolbar">
        <div className="filter-tabs">
          {[
            ["open", "Da fare"],
            ["today", "Oggi e scadute"],
            ["done", "Completate"],
          ].map(([value, label]) => (
            <button
              aria-pressed={filter === value}
              className={filter === value ? "is-active" : ""}
              key={value}
              onClick={() => setFilter(value)}
              type="button"
            >
              {label}
            </button>
          ))}
        </div>
        <div className="toolbar-filters">
          <select
            aria-label="Filtra per contatto"
            onChange={(event) => setContactId(event.target.value)}
            value={contactId}
          >
            <option value="">Tutti i contatti</option>
            {contacts.map((contact) => (
              <option key={contact.id} value={contact.id}>
                {contact.name}
              </option>
            ))}
          </select>
        </div>
      </div>
      {visible.length ? (
        <TaskList
          contacts={contacts}
          onEdit={onEdit}
          onToggle={onToggle}
          saving={saving}
          tasks={visible}
          works={works}
        />
      ) : (
        <div className="empty-state">
          <h2>
            {filter === "done"
              ? "Nessuna attività completata"
              : "Tutto in ordine"}
          </h2>
          <p>
            {query
              ? "Nessuna attività corrisponde alla ricerca."
              : "Aggiungi il prossimo passo per un contatto o un lavoro."}
          </p>
          <button className="primary-action" onClick={onCreate} type="button">
            Nuova attività
          </button>
        </div>
      )}
    </section>
  );
}
