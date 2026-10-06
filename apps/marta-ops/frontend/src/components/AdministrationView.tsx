import { useMemo } from "react";
import { useViewState } from "../lib/viewState";
import type { AdminFilter } from "../navigation";
import { daysFromToday, formatMoney } from "../format";
import { CONTRACT_OPTIONS, PAYMENT_OPTIONS } from "../options";
import type { Collaboration, ContractStatus, PaymentStatus } from "../types";
import { Icon } from "../Icon";

const PAYMENT_PRIORITY: Record<PaymentStatus, number> = {
  overdue: 0,
  to_invoice: 1,
  invoiced: 2,
  not_due: 3,
  paid: 4,
};

function contractNeedsAttention(work: Collaboration) {
  return (
    ["confirmed", "production", "approval", "scheduled", "published"].includes(
      work.phase,
    ) && !["signed", "not_needed"].includes(work.contract_status)
  );
}

function rightsNeedAttention(work: Collaboration) {
  return (
    Boolean(work.rights_expiry_date) &&
    daysFromToday(work.rights_expiry_date) <= 30
  );
}

function needsAttention(work: Collaboration) {
  return (
    ["to_invoice", "invoiced", "overdue"].includes(work.payment_status) ||
    contractNeedsAttention(work) ||
    rightsNeedAttention(work)
  );
}

function attentionLabels(work: Collaboration) {
  const labels: string[] = [];
  if (work.payment_status === "to_invoice") labels.push("Da fatturare");
  if (work.payment_status === "invoiced") labels.push("Incasso da seguire");
  if (work.payment_status === "overdue") labels.push("Pagamento scaduto");
  if (contractNeedsAttention(work)) labels.push("Contratto da completare");
  if (rightsNeedAttention(work))
    labels.push(
      daysFromToday(work.rights_expiry_date) < 0
        ? "Diritti scaduti"
        : "Diritti in scadenza",
    );
  return labels;
}

export function AdministrationView({
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
  onUpdate: (id: string, changes: Record<string, unknown>) => Promise<void>;
}) {
  const [filter, setFilter] = useViewState<AdminFilter>(
    "admin.filter",
    "attention",
  );
  const needle = query.trim().toLocaleLowerCase("it");
  const visible = useMemo(
    () =>
      items
        .filter(
          (work) =>
            (filter === "all" ||
              (filter === "attention" && needsAttention(work)) ||
              (filter === "receivables" &&
                ["invoiced", "overdue"].includes(work.payment_status)) ||
              work.payment_status === filter) &&
            (!needle ||
              [work.title, work.partner, work.next_action]
                .join(" ")
                .toLocaleLowerCase("it")
                .includes(needle)),
        )
        .sort(
          (a, b) =>
            PAYMENT_PRIORITY[a.payment_status] -
              PAYMENT_PRIORITY[b.payment_status] ||
            (a.rights_expiry_date || "9999").localeCompare(
              b.rights_expiry_date || "9999",
            ) ||
            a.title.localeCompare(b.title, "it"),
        ),
    [filter, items, needle],
  );
  const totalFor = (...statuses: PaymentStatus[]) =>
    items
      .filter((work) => statuses.includes(work.payment_status))
      .reduce((total, work) => total + work.value_minor, 0);
  const attentionCount = items.filter(needsAttention).length;

  return (
    <section className="page administration-page">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Incassi, contratti e diritti</p>
          <h1>
            Amministrazione{" "}
            <span className="heading-count">{visible.length}</span>
          </h1>
        </div>
        <span className="page-total">
          {attentionCount} <small>attenzioni</small>
        </span>
      </header>

      <div
        className="metric-strip admin-metrics"
        aria-label="Sintesi amministrativa"
      >
        <div>
          <span>{formatMoney(totalFor("to_invoice"), true)}</span>
          <small>da fatturare</small>
        </div>
        <div>
          <span>{formatMoney(totalFor("invoiced", "overdue"), true)}</span>
          <small>da incassare</small>
        </div>
        <div>
          <span>{formatMoney(totalFor("overdue"), true)}</span>
          <small>scaduto</small>
        </div>
      </div>

      <div className="view-toolbar">
        <div
          className="filter-tabs admin-filter-tabs"
          aria-label="Filtro amministrazione"
        >
          {(
            [
              ["attention", "Da gestire"],
              ["to_invoice", "Da fatturare"],
              ["receivables", "Da incassare"],
              ["invoiced", "Fatturati"],
              ["overdue", "Scaduti"],
              ["paid", "Incassati"],
              ["all", "Tutti"],
            ] as Array<[AdminFilter, string]>
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
      </div>

      {visible.length ? (
        <div className="admin-table">
          <div className="admin-list-header" aria-hidden="true">
            <span>Lavoro</span>
            <span>Pagamento</span>
            <span>Contratto</span>
            <span>Scadenza diritti</span>
            <span>Valore</span>
            <span />
          </div>
          <div className="admin-list">
            {visible.map((work) => {
              const labels = attentionLabels(work);
              return (
                <article className="admin-row" key={work.id}>
                  <button
                    className="admin-identity"
                    onClick={() => onOpen(work)}
                    type="button"
                  >
                    <strong>{work.title}</strong>
                    <span>{work.partner || "Senza partner"}</span>
                    {labels.length > 0 && <small>{labels.join(" · ")}</small>}
                  </button>
                  <label className="admin-field">
                    <span>Pagamento</span>
                    <select
                      aria-label={`Pagamento di ${work.title}`}
                      disabled={saving}
                      onChange={(event) =>
                        void onUpdate(work.id, {
                          payment_status: event.target.value as PaymentStatus,
                        }).catch(() => undefined)
                      }
                      value={work.payment_status}
                    >
                      {PAYMENT_OPTIONS.map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="admin-field">
                    <span>Contratto</span>
                    <select
                      aria-label={`Contratto di ${work.title}`}
                      disabled={saving}
                      onChange={(event) =>
                        void onUpdate(work.id, {
                          contract_status: event.target.value as ContractStatus,
                        }).catch(() => undefined)
                      }
                      value={work.contract_status}
                    >
                      {CONTRACT_OPTIONS.map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="admin-field admin-rights">
                    <span>Scadenza diritti</span>
                    <input
                      aria-label={`Scadenza diritti di ${work.title}`}
                      className={rightsNeedAttention(work) ? "is-warning" : ""}
                      disabled={saving}
                      onChange={(event) =>
                        void onUpdate(work.id, {
                          rights_expiry_date: event.target.value,
                        }).catch(() => undefined)
                      }
                      type="date"
                      value={work.rights_expiry_date}
                    />
                  </label>
                  <strong className="admin-value">
                    {formatMoney(work.value_minor, true)}
                  </strong>
                  <button
                    aria-label={`Apri ${work.title}`}
                    className="icon-action admin-open"
                    onClick={() => onOpen(work)}
                    type="button"
                  >
                    <Icon name="arrow" size={16} />
                  </button>
                </article>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="empty-state">
          <h2>
            {filter === "attention" ? "Tutto in ordine" : "Nessun lavoro qui"}
          </h2>
          <p>
            {query
              ? "Nessun lavoro corrisponde alla ricerca."
              : "Non ci sono elementi per questo filtro amministrativo."}
          </p>
        </div>
      )}
    </section>
  );
}
