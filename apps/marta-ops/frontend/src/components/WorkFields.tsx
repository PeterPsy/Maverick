import {
  CONTRACT_OPTIONS,
  KIND_OPTIONS,
  PAYMENT_OPTIONS,
  PHASE_OPTIONS,
} from "../options";
import type { Collaboration, Contact, WorkDraft } from "../types";

export function workDraft(
  item: Collaboration | null,
  preset: Partial<WorkDraft> = {},
): WorkDraft {
  if (!item)
    return {
      title: "",
      partner: "",
      partner_email: "",
      contact_id: "",
      kind: "partnership",
      phase: "lead",
      next_action: "",
      due_date: "",
      value_euros: "",
      payment_status: "not_due",
      contract_status: "not_needed",
      rights_expiry_date: "",
      notes: "",
      ...preset,
    };
  return {
    title: item.title,
    partner: item.partner,
    partner_email: item.partner_email || "",
    contact_id: item.contact_id || "",
    kind: item.kind,
    phase: item.phase,
    next_action: item.next_action,
    due_date: item.due_date,
    value_euros: item.value_minor ? (item.value_minor / 100).toFixed(2) : "",
    payment_status: item.payment_status,
    contract_status: item.contract_status,
    rights_expiry_date: item.rights_expiry_date,
    notes: item.notes,
  };
}

export function WorkFields({
  draft,
  contacts,
  setDraft,
}: {
  draft: WorkDraft;
  contacts: Contact[];
  setDraft: (update: (current: WorkDraft) => WorkDraft) => void;
}) {
  const set = <K extends keyof WorkDraft>(key: K, value: WorkDraft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));
  function selectContact(id: string) {
    const contact = contacts.find((item) => item.id === id);
    setDraft((current) => ({
      ...current,
      contact_id: id,
      ...(contact
        ? {
            partner: contact.company || contact.name,
            partner_email: contact.email,
          }
        : {}),
    }));
  }
  return (
    <div className="form-grid">
      <label className="field is-wide">
        <span>Titolo</span>
        <input
          maxLength={160}
          onChange={(event) => set("title", event.target.value)}
          placeholder="Es. Partnership autunno"
          required
          value={draft.title}
        />
      </label>
      <label className="field is-wide">
        <span>Contatto collegato</span>
        <select
          onChange={(event) => selectContact(event.target.value)}
          value={draft.contact_id}
        >
          <option value="">Nessun contatto</option>
          {contacts
            .filter(
              (contact) => !contact.archived || contact.id === draft.contact_id,
            )
            .map((contact) => (
              <option key={contact.id} value={contact.id}>
                {contact.name}
                {contact.company ? ` · ${contact.company}` : ""}
              </option>
            ))}
        </select>
      </label>
      <label className="field">
        <span>Partner</span>
        <input
          maxLength={160}
          onChange={(event) => set("partner", event.target.value)}
          placeholder="Brand o progetto"
          value={draft.partner}
        />
      </label>
      <label className="field">
        <span>Email partner</span>
        <input
          maxLength={320}
          onChange={(event) => set("partner_email", event.target.value)}
          type="email"
          value={draft.partner_email}
        />
      </label>
      <label className="field">
        <span>Tipo</span>
        <select
          onChange={(event) =>
            set("kind", event.target.value as WorkDraft["kind"])
          }
          value={draft.kind}
        >
          {KIND_OPTIONS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Fase</span>
        <select
          onChange={(event) =>
            set("phase", event.target.value as WorkDraft["phase"])
          }
          value={draft.phase}
        >
          {PHASE_OPTIONS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label className="field is-wide">
        <span>Prossima azione</span>
        <input
          maxLength={240}
          onChange={(event) => set("next_action", event.target.value)}
          placeholder="Chi fa cosa?"
          value={draft.next_action}
        />
      </label>
      <label className="field">
        <span>Scadenza</span>
        <input
          onChange={(event) => set("due_date", event.target.value)}
          type="date"
          value={draft.due_date}
        />
      </label>
      <label className="field">
        <span>Valore €</span>
        <input
          inputMode="decimal"
          onChange={(event) => set("value_euros", event.target.value)}
          pattern="[0-9]+([.,][0-9]{1,2})?"
          placeholder="0,00"
          value={draft.value_euros}
        />
      </label>
      <label className="field">
        <span>Pagamento</span>
        <select
          onChange={(event) =>
            set(
              "payment_status",
              event.target.value as WorkDraft["payment_status"],
            )
          }
          value={draft.payment_status}
        >
          {PAYMENT_OPTIONS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Contratto</span>
        <select
          onChange={(event) =>
            set(
              "contract_status",
              event.target.value as WorkDraft["contract_status"],
            )
          }
          value={draft.contract_status}
        >
          {CONTRACT_OPTIONS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Scadenza diritti</span>
        <input
          onChange={(event) => set("rights_expiry_date", event.target.value)}
          type="date"
          value={draft.rights_expiry_date}
        />
      </label>
      <label className="field is-wide">
        <span>Note operative</span>
        <textarea
          maxLength={4000}
          onChange={(event) => set("notes", event.target.value)}
          rows={3}
          value={draft.notes}
        />
      </label>
    </div>
  );
}
