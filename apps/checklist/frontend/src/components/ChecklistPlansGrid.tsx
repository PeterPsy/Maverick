import { CheckCircle2, Circle, CircleAlert, CircleDotDashed, CircleX, ExternalLink } from 'lucide-react';
import type { DragEvent } from 'react';
import { checklistDragPayloadFromItem, writeChecklistDragData } from '../lib/checklistDragDrop';
import type { AgentSubtask, AgentTask, ChecklistItem } from '../types';

interface ChecklistPlansGridProps {
  items: ChecklistItem[];
  onOpenChecklist: (item: ChecklistItem) => void;
}

export function ChecklistPlansGrid({ items, onOpenChecklist }: ChecklistPlansGridProps) {
  return (
    <section aria-labelledby="checklist-plans-heading" className="checklist-plans-view">
      <header className="detail-header checklist-plans-header">
        <div className="detail-title-block">
          <h2 id="checklist-plans-heading">Agent Plans</h2>
          <span className="detail-title-separator" aria-hidden="true" />
          <p>
            {items.length} {items.length === 1 ? 'plan' : 'plans'} available in this workspace.
          </p>
        </div>
      </header>

      <div className="checklist-plans-grid">
        {items.map((item) => (
          <ChecklistPlanCard item={item} key={item.id} onOpenChecklist={onOpenChecklist} />
        ))}
      </div>
    </section>
  );
}

function ChecklistPlanCard({
  item,
  onOpenChecklist,
}: {
  item: ChecklistItem;
  onOpenChecklist: (item: ChecklistItem) => void;
}) {
  const isCompleted = item.status === 'completed' || (item.task_count > 0 && item.checked_count >= item.task_count);
  const displayStatus = isCompleted ? 'completed' : item.status;

  function handleDragStart(event: DragEvent<HTMLElement>) {
    writeChecklistDragData(event.dataTransfer, checklistDragPayloadFromItem(item));
  }

  return (
    <article className="checklist-plan-card" draggable onDragStart={handleDragStart}>
      <header className="checklist-plan-card__header">
        <div className="checklist-plan-card__title-group">
          <p className="checklist-kicker">{item.mode.replace('_', ' ')}</p>
          <h2 className={isCompleted ? 'is-completed' : ''}>{item.title || 'Checklist'}</h2>
          {item.summary ? <p>{item.summary}</p> : null}
        </div>
        <button
          aria-label={`Open ${item.title || 'Checklist'}`}
          className="checklist-mini-button checklist-plan-card__open"
          onClick={() => onOpenChecklist(item)}
          type="button"
        >
          <ExternalLink size={15} aria-hidden="true" />
          <span>Open</span>
        </button>
      </header>

      <div className="checklist-plan-card__meta" aria-label="Checklist status">
        <span className={isCompleted ? 'is-completed' : ''}>{displayStatus.replace('-', ' ')}</span>
        <span>{item.priority}</span>
        <span>
          {item.checked_count}/{item.task_count}
        </span>
      </div>

      <div className="checklist-plan-card__body" tabIndex={0}>
        {item.sections.length ? (
          item.sections.map((section) => (
            <section className="checklist-plan-card__section" key={section.id}>
              {section.title ? <h3>{section.title}</h3> : null}
              {section.tasks.length ? (
                <ul className="checklist-plan-card__tasks">
                  {section.tasks.map((task, index) => (
                    <TaskPreview index={index} key={task.id} task={task} />
                  ))}
                </ul>
              ) : (
                <p className="checklist-plan-card__empty">No tasks.</p>
              )}
            </section>
          ))
        ) : (
          <p className="checklist-plan-card__empty">No sections.</p>
        )}
      </div>
    </article>
  );
}

function TaskPreview({ index, task }: { index: number; task: AgentTask }) {
  const title = task.title || `Task ${index + 1}`;

  return (
    <li className="checklist-plan-card__task">
      <div className="checklist-plan-card__task-row">
        <span className="checklist-plan-card__status" aria-hidden="true">
          {statusIcon(task.status)}
        </span>
        <span className="checklist-plan-card__task-copy">
          <strong className={task.status === 'completed' ? 'is-completed' : ''}>{title}</strong>
          {task.description ? <span>{task.description}</span> : null}
        </span>
      </div>

      {task.subtasks.length ? (
        <ul className="checklist-plan-card__subtasks">
          {task.subtasks.map((subtask, index) => (
            <SubtaskPreview index={index} key={subtask.id} subtask={subtask} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function SubtaskPreview({ index, subtask }: { index: number; subtask: AgentSubtask }) {
  return (
    <li className="checklist-plan-card__subtask">
      <span className="checklist-plan-card__status" aria-hidden="true">
        {statusIcon(subtask.status)}
      </span>
      <span className="checklist-plan-card__task-copy">
        <strong className={subtask.status === 'completed' ? 'is-completed' : ''}>
          {subtask.title || `Subtask ${index + 1}`}
        </strong>
        {subtask.description ? <span>{subtask.description}</span> : null}
      </span>
    </li>
  );
}

function statusIcon(status: string) {
  if (status === 'completed') {
    return <CheckCircle2 size={16} />;
  }
  if (status === 'in-progress') {
    return <CircleDotDashed size={16} />;
  }
  if (status === 'need-help' || status === 'blocked') {
    return <CircleAlert size={16} />;
  }
  if (status === 'failed') {
    return <CircleX size={16} />;
  }
  return <Circle size={16} />;
}
