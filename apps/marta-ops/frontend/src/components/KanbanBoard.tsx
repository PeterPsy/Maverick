// Adapted from Atomic CRM DealListContent, DealColumn and DealCard at a863e2a.
// Copyright (c) 2024-present, Francois Zaninotto, Marmelab. MIT; see THIRD_PARTY_NOTICES.md.
import {
  DragDropContext,
  Draggable,
  Droppable,
  type DropResult,
} from "@hello-pangea/dnd";
import { useMemo, useState } from "react";
import { Icon } from "../Icon";
import { daysFromToday, dueLabel, formatMoney } from "../format";
import {
  beforeIdForMove,
  CLOSED_PHASES,
  groupByPhase,
  moveLocal,
  type Pipeline,
  type WorkFilter,
} from "../lib/pipeline";
import { PHASE_OPTIONS } from "../options";
import type { Collaboration, CollaborationPhase } from "../types";

export type MoveWork = (
  id: string,
  phase: CollaborationPhase,
  beforeId: string,
  expectedPhase: CollaborationPhase,
) => Promise<void>;

export function KanbanBoard({
  items,
  filter,
  phaseFilter,
  saving,
  onOpen,
  onMove,
  onCreate,
}: {
  items: Collaboration[];
  filter: WorkFilter;
  phaseFilter: string;
  saving: boolean;
  onOpen: (item: Collaboration) => void;
  onMove: MoveWork;
  onCreate: (phase?: CollaborationPhase) => void;
}) {
  const baseColumns = useMemo(() => groupByPhase(items), [items]);
  const [optimistic, setOptimistic] = useState<Pipeline | null>(null);
  const columns = optimistic || baseColumns;
  const stages = PHASE_OPTIONS.filter(
    ([phase]) =>
      (!phaseFilter || phase === phaseFilter) &&
      (filter === "all" ||
        (filter === "closed"
          ? CLOSED_PHASES.has(phase)
          : !CLOSED_PHASES.has(phase))),
  );
  const busy = saving || Boolean(optimistic);

  async function dragEnd({ destination, source, draggableId }: DropResult) {
    if (
      !destination ||
      busy ||
      (source.droppableId === destination.droppableId &&
        source.index === destination.index)
    )
      return;
    const target = destination.droppableId as CollaborationPhase;
    const beforeId = beforeIdForMove(
      columns,
      draggableId,
      target,
      destination.index,
    );
    setOptimistic(moveLocal(columns, draggableId, target, destination.index));
    try {
      await onMove(
        draggableId,
        target,
        beforeId,
        source.droppableId as CollaborationPhase,
      );
    } catch {
      /* Restore the saved columns; the app displays the error. */
    } finally {
      setOptimistic(null);
    }
  }

  return (
    <DragDropContext onDragEnd={(result) => void dragEnd(result)}>
      <div aria-label="Pipeline lavori" className="kanban-board">
        {stages.map(([phase, label]) => (
          <section className="kanban-column" key={phase}>
            <header className="kanban-heading">
              <div>
                <h2>
                  <i data-phase={phase} />
                  {label}
                  <span>{columns[phase].length}</span>
                </h2>
                <small>
                  {formatMoney(
                    columns[phase].reduce(
                      (sum, work) => sum + work.value_minor,
                      0,
                    ),
                    true,
                  )}
                </small>
              </div>
              <button
                aria-label={`Nuovo lavoro: ${label}`}
                className="icon-action"
                disabled={busy}
                onClick={() => onCreate(phase)}
                type="button"
              >
                <Icon name="plus" size={16} />
              </button>
            </header>
            <Droppable droppableId={phase} isDropDisabled={busy}>
              {(provided, snapshot) => (
                <div
                  className={`kanban-dropzone ${snapshot.isDraggingOver ? "is-over" : ""}`}
                  ref={provided.innerRef}
                  {...provided.droppableProps}
                >
                  {columns[phase].map((work, index) => (
                    <Draggable
                      draggableId={work.id}
                      index={index}
                      isDragDisabled={busy}
                      key={work.id}
                    >
                      {(drag, state) => (
                        <article
                          className={`kanban-card ${state.isDragging ? "is-dragging" : ""}`}
                          ref={drag.innerRef}
                          {...drag.draggableProps}
                        >
                          <div className="kanban-card-top">
                            <span className="kanban-partner">
                              {work.partner || "Senza partner"}
                            </span>
                            <button
                              aria-label={`Sposta ${work.title}`}
                              className="drag-handle"
                              type="button"
                              {...drag.dragHandleProps}
                            >
                              <Icon name="grip" size={16} />
                            </button>
                          </div>
                          <button
                            className="kanban-title"
                            onClick={() => onOpen(work)}
                            type="button"
                          >
                            {work.title}
                          </button>
                          {work.next_action && (
                            <p className="kanban-next">{work.next_action}</p>
                          )}
                          <div className="kanban-meta">
                            <span>{formatMoney(work.value_minor, true)}</span>
                            <span
                              className={
                                daysFromToday(work.due_date) < 0
                                  ? "is-danger"
                                  : ""
                              }
                            >
                              {dueLabel(work.due_date)}
                            </span>
                          </div>
                          {work.deliverables.length > 0 && (
                            <div className="kanban-progress">
                              <span
                                style={{
                                  width: `${(100 * work.deliverables.filter((item) => item.status === "published").length) / work.deliverables.length}%`,
                                }}
                              />
                              <small>
                                {
                                  work.deliverables.filter(
                                    (item) => item.status === "published",
                                  ).length
                                }
                                /{work.deliverables.length} consegne
                              </small>
                            </div>
                          )}
                          <select
                            aria-label={`Fase di ${work.title}`}
                            className="kanban-phase"
                            disabled={busy}
                            onChange={(event) => {
                              void onMove(
                                work.id,
                                event.target.value as CollaborationPhase,
                                "",
                                work.phase,
                              ).catch(() => undefined);
                            }}
                            value={work.phase}
                          >
                            {PHASE_OPTIONS.map(([value, title]) => (
                              <option key={value} value={value}>
                                {title}
                              </option>
                            ))}
                          </select>
                        </article>
                      )}
                    </Draggable>
                  ))}
                  {provided.placeholder}
                  {!columns[phase].length && (
                    <button
                      className="kanban-add"
                      disabled={busy}
                      onClick={() => onCreate(phase)}
                      type="button"
                    >
                      <Icon name="plus" size={14} />
                      Aggiungi lavoro
                    </button>
                  )}
                </div>
              )}
            </Droppable>
          </section>
        ))}
      </div>
    </DragDropContext>
  );
}
