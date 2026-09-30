import { daysFromToday, formatMoney, todayIso } from "../format";
import { CLOSED_PHASES } from "../lib/pipeline";
import type { Collaboration, MartaOpsState, Task } from "../types";
import { WorkRow } from "./WorkRow";
import { TaskList } from "./TaskList";
import { ActivityFeed } from "./ActivityFeed";
import { PipelineSummary } from "./PipelineSummary";

export function TodayView({
  state,
  saving,
  onCreate,
  onOpen,
  onWorks,
  onTasks,
  onNewTask,
  onToggleTask,
  onEditTask,
}: {
  state: MartaOpsState;
  saving: boolean;
  onCreate: () => void;
  onOpen: (item: Collaboration) => void;
  onWorks: () => void;
  onTasks: () => void;
  onNewTask: () => void;
  onToggleTask: (task: Task) => Promise<void>;
  onEditTask: (task: Task) => void;
}) {
  const active = state.collaborations.filter(
    (item) => !CLOSED_PHASES.has(item.phase),
  );
  const focus = state.collaborations
    .filter(
      (item) =>
        item.payment_status === "overdue" ||
        (!CLOSED_PHASES.has(item.phase) &&
          (daysFromToday(item.due_date) <= 1 ||
            item.phase === "approval" ||
            daysFromToday(item.rights_expiry_date) <= 7 ||
            (["confirmed", "production"].includes(item.phase) &&
              !["signed", "not_needed"].includes(item.contract_status)))),
    )
    .sort((a, b) => daysFromToday(a.due_date) - daysFromToday(b.due_date));
  const upcoming = active
    .filter(
      (item) =>
        daysFromToday(item.due_date) > 1 && daysFromToday(item.due_date) <= 7,
    )
    .sort((a, b) => daysFromToday(a.due_date) - daysFromToday(b.due_date));
  const tasks = state.tasks
    .filter((task) => !task.done)
    .sort((a, b) => (a.due_date || "9999").localeCompare(b.due_date || "9999"));
  const urgentTasks = tasks.filter((task) => daysFromToday(task.due_date) <= 0);
  const toCollect = state.collaborations
    .filter((item) => ["invoiced", "overdue"].includes(item.payment_status))
    .reduce((sum, item) => sum + item.value_minor, 0);
  const dateLabel = new Intl.DateTimeFormat("it-IT", {
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(new Date(`${todayIso()}T12:00:00`));
  return (
    <section className="page today-page">
      <header className="page-heading">
        <div>
          <p className="eyebrow">{dateLabel}</p>
          <h1>Oggi</h1>
        </div>
        <button className="secondary-action" onClick={onNewTask} type="button">
          Nuova attività
        </button>
      </header>
      <div className="metric-strip" aria-label="Sintesi operativa">
        <div>
          <span>{focus.length + urgentTasks.length}</span>
          <small>da gestire</small>
        </div>
        <div>
          <span>{upcoming.length}</span>
          <small>lavori entro 7 giorni</small>
        </div>
        <div>
          <span>{formatMoney(toCollect, true)}</span>
          <small>da incassare</small>
        </div>
      </div>
      <div className="dashboard-grid">
        <div className="dashboard-main">
          <section className="dashboard-section">
            <div className="section-heading">
              <h2>Richiedono attenzione</h2>
              <span>{focus.length}</span>
            </div>
            {focus.length ? (
              <div className="row-list">
                {focus.map((item) => (
                  <WorkRow
                    compact
                    item={item}
                    key={item.id}
                    onOpen={() => onOpen(item)}
                  />
                ))}
              </div>
            ) : (
              <div className="empty-state is-inline">
                <p>
                  {state.collaborations.length
                    ? "Nessuna urgenza sui lavori."
                    : "Crea la tua prima collaborazione."}
                </p>
                <button
                  className="secondary-action"
                  onClick={onCreate}
                  type="button"
                >
                  Nuovo lavoro
                </button>
              </div>
            )}
          </section>
          {upcoming.length > 0 && (
            <section className="dashboard-section">
              <div className="section-heading">
                <h2>Questa settimana</h2>
                <span>{upcoming.length}</span>
              </div>
              <div className="row-list">
                {upcoming.map((item) => (
                  <WorkRow
                    compact
                    item={item}
                    key={item.id}
                    onOpen={() => onOpen(item)}
                  />
                ))}
              </div>
            </section>
          )}
          <PipelineSummary items={state.collaborations} onOpen={onWorks} />
          <section className="dashboard-section">
            <div className="section-heading">
              <h2>Ultime attività</h2>
            </div>
            <ActivityFeed entries={state.activity.slice(-8)} />
          </section>
        </div>
        <aside className="dashboard-aside">
          <section className="dashboard-section">
            <div className="section-heading">
              <h2>Da fare</h2>
              <span>{tasks.length}</span>
              <button className="text-action" onClick={onTasks} type="button">
                Tutte
              </button>
            </div>
            {tasks.length ? (
              <TaskList
                contacts={state.contacts}
                onEdit={onEditTask}
                onToggle={onToggleTask}
                saving={saving}
                tasks={tasks.slice(0, 8)}
                works={state.collaborations}
              />
            ) : (
              <div className="empty-state is-inline">
                <p>Nessun follow-up aperto.</p>
                <button
                  className="secondary-action"
                  onClick={onNewTask}
                  type="button"
                >
                  Aggiungi
                </button>
              </div>
            )}
          </section>
          <div className="workspace-counts">
            <span>
              <strong>{active.length}</strong> lavori aperti
            </span>
            <span>
              <strong>
                {state.contacts.filter((contact) => !contact.archived).length}
              </strong>{" "}
              contatti attivi
            </span>
          </div>
        </aside>
      </div>
    </section>
  );
}
