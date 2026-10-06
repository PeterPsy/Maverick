import { useMemo } from "react";
import { useViewState } from "../lib/viewState";
import type { DeliveryFilter } from "../navigation";
import { daysFromToday, dueLabel } from "../format";
import { DELIVERABLE_OPTIONS, labelFor } from "../options";
import type { Collaboration, Deliverable, DeliverableStatus } from "../types";

type DeliveryEntry = { deliverable: Deliverable; work: Collaboration };

const OPEN_STATUSES: DeliverableStatus[] = [
  "planned",
  "in_progress",
  "approval",
  "scheduled",
];

export function DeliveriesView({
  items,
  query,
  saving,
  onOpen,
  onUpdate,
}: {
  items: Collaboration[];
  query: string;
  saving: boolean;
  onOpen: (work: Collaboration) => void;
  onUpdate: (
    workId: string,
    deliverableId: string,
    changes: Record<string, unknown>,
  ) => Promise<void>;
}) {
  const [filter, setFilter] = useViewState<DeliveryFilter>(
    "deliveries.filter",
    "open",
  );
  const [workId, setWorkId] = useViewState("deliveries.workId", "");
  const entries = useMemo<DeliveryEntry[]>(
    () =>
      items.flatMap((work) =>
        work.deliverables.map((deliverable) => ({ deliverable, work })),
      ),
    [items],
  );
  const needle = query.trim().toLocaleLowerCase("it");
  const visible = entries
    .filter(({ deliverable, work }) => {
      const matchesFilter =
        filter === "all" ||
        (filter === "open" && deliverable.status !== "published") ||
        (filter === "published" && deliverable.status === "published") ||
        (filter === "approval" && deliverable.status === "approval") ||
        (filter === "overdue" &&
          deliverable.status !== "published" &&
          daysFromToday(deliverable.due_date) < 0);
      return (
        matchesFilter &&
        (!workId || work.id === workId) &&
        (!needle ||
          [deliverable.title, work.title, work.partner]
            .join(" ")
            .toLocaleLowerCase("it")
            .includes(needle))
      );
    })
    .sort((a, b) =>
      (a.deliverable.due_date || "9999").localeCompare(
        b.deliverable.due_date || "9999",
      ),
    );
  const statuses =
    filter === "approval"
      ? (["approval"] as DeliverableStatus[])
      : filter === "published"
        ? (["published"] as DeliverableStatus[])
        : filter === "all"
          ? [...OPEN_STATUSES, "published"]
          : OPEN_STATUSES;
  const overdue = entries.filter(
    ({ deliverable }) =>
      deliverable.status !== "published" &&
      daysFromToday(deliverable.due_date) < 0,
  ).length;
  const dueSoon = entries.filter(({ deliverable }) => {
    const days = daysFromToday(deliverable.due_date);
    return deliverable.status !== "published" && days >= 0 && days <= 7;
  }).length;
  const approvals = entries.filter(
    ({ deliverable }) => deliverable.status === "approval",
  ).length;
  const worksWithDeliveries = items.filter((work) => work.deliverables.length);

  return (
    <section className="page deliveries-page">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Produzione e approvazioni</p>
          <h1>
            Consegne <span className="heading-count">{visible.length}</span>
          </h1>
        </div>
        <span className="page-total">
          {overdue} <small>in ritardo</small>
        </span>
      </header>

      <div
        className="metric-strip delivery-metrics"
        aria-label="Sintesi consegne"
      >
        <div>
          <span>{overdue}</span>
          <small>in ritardo</small>
        </div>
        <div>
          <span>{dueSoon}</span>
          <small>entro 7 giorni</small>
        </div>
        <div>
          <span>{approvals}</span>
          <small>in approvazione</small>
        </div>
      </div>

      <div className="view-toolbar">
        <div className="filter-tabs" aria-label="Stato consegne">
          {(
            [
              ["open", "Aperte"],
              ["overdue", "Scadute"],
              ["approval", "Da approvare"],
              ["all", "Tutte"],
              ["published", "Pubblicate"],
            ] as Array<[DeliveryFilter, string]>
          ).map(([value, label]) => (
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
            aria-label="Filtra consegne per lavoro"
            onChange={(event) => setWorkId(event.target.value)}
            value={workId}
          >
            <option value="">Tutti i lavori</option>
            {worksWithDeliveries.map((work) => (
              <option key={work.id} value={work.id}>
                {work.title}
              </option>
            ))}
          </select>
        </div>
      </div>

      {visible.length ? (
        <div className="delivery-board">
          {statuses.map((status) => {
            const column = visible.filter(
              ({ deliverable }) => deliverable.status === status,
            );
            return (
              <section className="delivery-column" key={status}>
                <header className="delivery-column-heading">
                  <h2>
                    <i data-status={status} />
                    {labelFor(DELIVERABLE_OPTIONS, status)}
                  </h2>
                  <span>{column.length}</span>
                </header>
                <div className="delivery-column-body">
                  {column.map(({ deliverable, work }) => {
                    const late =
                      deliverable.status !== "published" &&
                      daysFromToday(deliverable.due_date) < 0;
                    return (
                      <article
                        className="delivery-card"
                        key={`${work.id}:${deliverable.id}`}
                      >
                        <button
                          aria-label={`Apri ${deliverable.title} in ${work.title}`}
                          className="delivery-card-title"
                          onClick={() => onOpen(work)}
                          type="button"
                        >
                          {deliverable.title}
                        </button>
                        <p>{work.title}</p>
                        <div className="delivery-card-meta">
                          <span>{work.partner || "Senza partner"}</span>
                          <span className={late ? "is-danger" : ""}>
                            {dueLabel(deliverable.due_date)}
                          </span>
                        </div>
                        <select
                          aria-label={`Stato di ${deliverable.title}`}
                          disabled={saving}
                          onChange={(event) =>
                            void onUpdate(work.id, deliverable.id, {
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
                      </article>
                    );
                  })}
                  {!column.length && (
                    <p className="delivery-column-empty">Nessuna consegna</p>
                  )}
                </div>
              </section>
            );
          })}
        </div>
      ) : (
        <div className="empty-state">
          <h2>
            {entries.length
              ? "Nessuna consegna qui"
              : "Nessuna consegna ancora"}
          </h2>
          <p>
            {entries.length
              ? "Modifica i filtri o la ricerca per vedere altre consegne."
              : "Aggiungi i deliverable dalla scheda di un lavoro."}
          </p>
        </div>
      )}
    </section>
  );
}
