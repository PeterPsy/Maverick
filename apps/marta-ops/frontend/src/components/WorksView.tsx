import { useMemo } from "react";
import { useViewState } from "../lib/viewState";
import { Icon } from "../Icon";
import { formatMoney } from "../format";
import { KIND_OPTIONS, PHASE_OPTIONS } from "../options";
import { visibleWorks, type WorkFilter } from "../lib/pipeline";
import type { Collaboration, CollaborationPhase } from "../types";
import { KanbanBoard, type MoveWork } from "./KanbanBoard";
import { WorkRow } from "./WorkRow";

export function WorksView({
  items,
  query,
  onCreate,
  onOpen,
  onMove,
  saving,
}: {
  items: Collaboration[];
  query: string;
  onCreate: (phase?: CollaborationPhase) => void;
  onOpen: (item: Collaboration) => void;
  onMove: MoveWork;
  saving: boolean;
}) {
  const [filter, setFilter] = useViewState<WorkFilter>("work.filter", "open");
  const [mode, setMode] = useViewState<"board" | "list">("work.mode", "board");
  const [kind, setKind] = useViewState("work.kind", "");
  const [phase, setPhase] = useViewState("work.phase", "");
  const visible = useMemo(
    () => visibleWorks(items, filter, query, kind, phase),
    [filter, items, query, kind, phase],
  );
  return (
    <section
      className={`page works-page ${mode === "board" ? "is-board" : ""}`}
    >
      <header className="page-heading">
        <div>
          <p className="eyebrow">Collaborazioni e progetti</p>
          <h1>
            Lavori <span className="heading-count">{visible.length}</span>
          </h1>
        </div>
        <span className="page-total">
          {formatMoney(
            visible.reduce((sum, work) => sum + work.value_minor, 0),
            true,
          )}{" "}
          <small>valore totale</small>
        </span>
      </header>
      <div className="view-toolbar">
        <div className="filter-tabs" aria-label="Stato lavori">
          {(
            [
              ["open", "Aperti"],
              ["all", "Tutti"],
              ["closed", "Chiusi"],
            ] as Array<[WorkFilter, string]>
          ).map(([value, label]) => (
            <button
              aria-pressed={filter === value}
              className={filter === value ? "is-active" : ""}
              key={value}
              onClick={() => {
                setFilter(value);
                setPhase("");
              }}
              type="button"
            >
              {label}
            </button>
          ))}
        </div>
        <div className="toolbar-filters">
          <select
            aria-label="Filtra per tipo"
            onChange={(event) => setKind(event.target.value)}
            value={kind}
          >
            <option value="">Tutti i tipi</option>
            {KIND_OPTIONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <select
            aria-label="Filtra per fase"
            onChange={(event) => {
              setPhase(event.target.value);
              if (event.target.value) setFilter("all");
            }}
            value={phase}
          >
            <option value="">Tutte le fasi</option>
            {PHASE_OPTIONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div aria-label="Vista lavori" className="view-switch">
          {(["board", "list"] as const).map((value) => (
            <button
              aria-label={value === "board" ? "Kanban" : "Elenco"}
              aria-pressed={mode === value}
              className={mode === value ? "is-active" : ""}
              key={value}
              onClick={() => setMode(value)}
              type="button"
            >
              <Icon name={value} size={16} />
            </button>
          ))}
        </div>
      </div>
      {query && (
        <p aria-live="polite" className="search-count">
          {visible.length} risultati per “{query}”
        </p>
      )}
      {mode === "board" ? (
        <KanbanBoard
          filter={filter}
          items={visible}
          onCreate={onCreate}
          onMove={onMove}
          onOpen={onOpen}
          phaseFilter={phase}
          saving={saving}
        />
      ) : (
        <>
          <div className="list-header" aria-hidden="true">
            <span>Lavoro</span>
            <span>Fase</span>
            <span>Prossima azione</span>
            <span>Data</span>
            <span>Valore</span>
            <span />
          </div>
          {visible.length ? (
            <div className="row-list work-table">
              {[...visible]
                .sort((a, b) =>
                  (a.due_date || "9999").localeCompare(b.due_date || "9999"),
                )
                .map((item) => (
                  <WorkRow
                    item={item}
                    key={item.id}
                    onOpen={() => onOpen(item)}
                  />
                ))}
            </div>
          ) : (
            <div className="empty-state">
              <h2>Nessun lavoro qui</h2>
              <p>
                {query
                  ? "Prova una ricerca diversa."
                  : "Crea la tua prossima collaborazione."}
              </p>
              <button
                className="primary-action"
                onClick={() => onCreate()}
                type="button"
              >
                Nuovo lavoro
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
