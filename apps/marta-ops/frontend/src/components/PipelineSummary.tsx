import { formatMoney } from "../format";
import { CLOSED_PHASES } from "../lib/pipeline";
import { PHASE_OPTIONS } from "../options";
import type { Collaboration, CollaborationPhase } from "../types";

const GROUPS: Array<[string, CollaborationPhase[]]> = [
  ["Da acquisire", ["lead", "proposal"]],
  ["In corso", ["confirmed", "production"]],
  ["In approvazione", ["approval"]],
  ["In uscita", ["scheduled", "published"]],
];

export function PipelineSummary({
  items,
  onOpen,
}: {
  items: Collaboration[];
  onOpen: () => void;
}) {
  const active = items.filter((item) => !CLOSED_PHASES.has(item.phase));
  const counts = GROUPS.map(([, phases]) =>
    active.filter((item) => phases.includes(item.phase)),
  );
  const max = Math.max(1, ...counts.map((group) => group.length));
  return (
    <section className="dashboard-section">
      <div className="section-heading">
        <h2>Pipeline</h2>
        <button className="text-action" onClick={onOpen} type="button">
          Apri lavori
        </button>
      </div>
      <div className="pipeline-summary">
        {GROUPS.map(([label], index) => (
          <div className="pipeline-summary-row" key={label}>
            <span>{label}</span>
            <div className="pipeline-bar">
              <i style={{ width: `${(100 * counts[index].length) / max}%` }} />
            </div>
            <strong>{counts[index].length}</strong>
            <small>
              {formatMoney(
                counts[index].reduce((sum, item) => sum + item.value_minor, 0),
                true,
              )}
            </small>
          </div>
        ))}
        <p className="muted-message">
          {active.filter((item) => item.phase === "paused").length > 0
            ? `${active.filter((item) => item.phase === "paused").length} lavori ${PHASE_OPTIONS.find(([phase]) => phase === "paused")?.[1].toLocaleLowerCase("it")}`
            : `${active.length} lavori aperti`}
        </p>
      </div>
    </section>
  );
}
