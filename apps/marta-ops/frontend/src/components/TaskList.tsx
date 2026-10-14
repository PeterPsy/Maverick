// Task completion and linked context follow Atomic CRM tasks/Task.tsx (MIT).
import { Icon } from "../Icon";
import { dueLabel, daysFromToday } from "../format";
import type { Collaboration, Contact, Task } from "../types";

export const TASK_KINDS: Array<[Task["kind"], string]> = [
  ["task", "Attività"],
  ["call", "Chiamata"],
  ["email", "Email"],
  ["meeting", "Incontro"],
];

export function TaskList({
  tasks,
  works,
  contacts,
  saving,
  onToggle,
  onEdit,
}: {
  tasks: Task[];
  works: Collaboration[];
  contacts: Contact[];
  saving: boolean;
  onToggle: (task: Task) => Promise<void>;
  onEdit: (task: Task) => void;
}) {
  return (
    <div className="task-list">
      {tasks.map((task) => {
        const contact = contacts.find((item) => item.id === task.contact_id);
        const work = works.find((item) => item.id === task.collaboration_id);
        return (
          <div
            className={`task-row ${task.done ? "is-done" : ""}`}
            key={task.id}
          >
            <button
              aria-label={
                task.done ? `Riapri ${task.title}` : `Completa ${task.title}`
              }
              aria-pressed={task.done}
              className={`deliverable-check ${task.done ? "is-done" : ""}`}
              disabled={saving}
              onClick={() => void onToggle(task).catch(() => undefined)}
              type="button"
            >
              {task.done && <Icon name="check" size={14} />}
            </button>
            <button
              className="task-identity"
              onClick={() => onEdit(task)}
              type="button"
            >
              <strong>{task.title}</strong>
              <small>
                {[
                  TASK_KINDS.find(([kind]) => kind === task.kind)?.[1],
                  contact?.name,
                  work?.title,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </small>
            </button>
            <span
              className={`task-date ${!task.done && daysFromToday(task.due_date) < 0 ? "is-danger" : ""}`}
            >
              {dueLabel(task.due_date)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
