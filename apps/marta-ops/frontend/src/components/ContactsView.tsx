import { useViewState } from "../lib/viewState";
import { formatMoney } from "../format";
import type { Collaboration, Contact } from "../types";
import { Avatar } from "./Avatar";

export function ContactsView({
  contacts,
  works,
  query,
  onOpen,
  onCreate,
}: {
  contacts: Contact[];
  works: Collaboration[];
  query: string;
  onOpen: (contact: Contact) => void;
  onCreate: () => void;
}) {
  const [archived, setArchived] = useViewState("contacts.archived", false);
  const [tag, setTag] = useViewState("contacts.tag", "");
  const tags = [...new Set(contacts.flatMap((contact) => contact.tags))].sort();
  const needle = query.trim().toLocaleLowerCase("it");
  const visible = contacts
    .filter(
      (contact) =>
        contact.archived === archived &&
        (!tag || contact.tags.includes(tag)) &&
        (!needle ||
          [
            contact.name,
            contact.company,
            contact.email,
            contact.role,
            ...contact.tags,
          ]
            .join(" ")
            .toLocaleLowerCase("it")
            .includes(needle)),
    )
    .sort((a, b) => a.name.localeCompare(b.name, "it"));
  return (
    <section className="page contacts-page">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Brand, agenzie e persone</p>
          <h1>
            Contatti <span className="heading-count">{visible.length}</span>
          </h1>
        </div>
        <button className="secondary-action" onClick={onCreate} type="button">
          Nuovo contatto
        </button>
      </header>
      <div className="view-toolbar">
        <div className="filter-tabs">
          <button
            aria-pressed={!archived}
            className={!archived ? "is-active" : ""}
            onClick={() => setArchived(false)}
            type="button"
          >
            Attivi
          </button>
          <button
            aria-pressed={archived}
            className={archived ? "is-active" : ""}
            onClick={() => setArchived(true)}
            type="button"
          >
            Archiviati
          </button>
        </div>
        <div className="toolbar-filters">
          <select
            aria-label="Filtra per tag"
            onChange={(event) => setTag(event.target.value)}
            value={tag}
          >
            <option value="">Tutti i tag</option>
            {tags.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </div>
      </div>
      {visible.length ? (
        <div className="contact-grid">
          {visible.map((contact) => {
            const linked = works.filter(
              (work) => work.contact_id === contact.id,
            );
            return (
              <button
                className="contact-card"
                key={contact.id}
                onClick={() => onOpen(contact)}
                type="button"
              >
                <div className="contact-card-heading">
                  <Avatar name={contact.name} />
                  <div>
                    <h2>{contact.name}</h2>
                    <p>
                      {[contact.role, contact.company]
                        .filter(Boolean)
                        .join(" · ") || "Contatto"}
                    </p>
                  </div>
                </div>
                <span className="contact-email">
                  {contact.email || contact.phone || "Nessun recapito"}
                </span>
                <div className="tag-list">
                  {contact.tags.map((value) => (
                    <span className="tag" key={value}>
                      {value}
                    </span>
                  ))}
                </div>
                <div className="contact-card-footer">
                  <span>
                    {linked.length} {linked.length === 1 ? "lavoro" : "lavori"}
                  </span>
                  <span>
                    {formatMoney(
                      linked.reduce((sum, work) => sum + work.value_minor, 0),
                      true,
                    )}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="empty-state">
          <h2>
            {query || tag
              ? "Nessun risultato"
              : archived
                ? "Nessun contatto archiviato"
                : "Le relazioni iniziano qui"}
          </h2>
          <p>
            {query || tag
              ? "Prova una ricerca o un tag diverso."
              : "Aggiungi il referente di un brand o di un’agenzia."}
          </p>
          {!archived && (
            <button className="primary-action" onClick={onCreate} type="button">
              Nuovo contatto
            </button>
          )}
        </div>
      )}
    </section>
  );
}
