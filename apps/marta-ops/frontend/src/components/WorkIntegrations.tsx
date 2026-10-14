import { Icon } from "../Icon";
import type {
  Collaboration,
  IntegrationOptions,
  IntegrationPreferences,
  LinkedDocument,
} from "../types";

function calendarValue(connectionId: string, calendarId: string) {
  return `${connectionId}::${calendarId}`;
}

function fileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function WorkIntegrations({
  item,
  options,
  preferences,
  saving,
  busy,
  canMail,
  canCalendar,
  onIntegrate,
  onOpenMail,
  onOpenCalendar,
  onOpenDocument,
  onPickDocument,
  onUnlinkDocument,
  onRefresh,
  onPreferenceChange,
}: {
  item: Collaboration;
  options: IntegrationOptions;
  preferences: IntegrationPreferences;
  saving: boolean;
  busy: string;
  canMail: boolean;
  canCalendar: boolean;
  onIntegrate: (target: "mail" | "calendar") => void;
  onOpenMail: () => void;
  onOpenCalendar: () => void;
  onOpenDocument: (document: LinkedDocument) => void;
  onPickDocument: () => void;
  onUnlinkDocument: (document: LinkedDocument) => void;
  onRefresh: () => void;
  onPreferenceChange: (changes: Record<string, string>) => void;
}) {
  const disabled = saving || Boolean(busy);
  const accountLabels = new Map(
    options.calendar_connections.map((connection) => [
      connection.id,
      connection.label,
    ]),
  );
  const selectedCalendar = calendarValue(
    preferences.calendar_connection_id,
    preferences.calendar_id,
  );

  return (
    <section className="integrations-section">
      <div className="section-heading integration-heading">
        <div>
          <h3>App collegate</h3>
          <p>Account, scadenze e file del lavoro.</p>
        </div>
        <button
          aria-label="Aggiorna connessioni"
          className="icon-action"
          disabled={disabled}
          onClick={onRefresh}
          type="button"
        >
          <Icon name="refresh" size={15} />
        </button>
      </div>

      <div className="integration-grid">
        <article className="integration-card">
          <div className="integration-card-title">
            <Icon name="mail" size={16} />
            <strong>Mail</strong>
          </div>
          <select
            aria-label="Account Mail"
            disabled={disabled || !options.mail_connections.length}
            onChange={(event) =>
              onPreferenceChange({ mail_connection_id: event.target.value })
            }
            value={preferences.mail_connection_id}
          >
            {!options.mail_connections.length && (
              <option value="">Nessun account disponibile</option>
            )}
            {options.mail_connections.map((connection) => (
              <option key={connection.id} value={connection.id}>
                {connection.label}
              </option>
            ))}
          </select>
          <div className="integration-card-actions">
            <button
              className="secondary-action"
              disabled={disabled || !canMail || !preferences.mail_connection_id}
              onClick={() => onIntegrate("mail")}
              type="button"
            >
              {busy === "mail"
                ? "Aggiorno…"
                : item.mail_draft.id
                  ? "Aggiorna bozza"
                  : "Crea bozza"}
            </button>
            {item.mail_draft.id && (
              <button
                aria-label="Apri bozza in Mail"
                className="icon-action"
                onClick={onOpenMail}
                type="button"
              >
                <Icon name="external" size={15} />
              </button>
            )}
          </div>
          <small>
            {item.documents.length
              ? `${item.documents.length} allegati dalla scheda lavoro`
              : "Nessun allegato"}
          </small>
        </article>

        <article className="integration-card">
          <div className="integration-card-title">
            <Icon name="calendar" size={16} />
            <strong>Calendario</strong>
          </div>
          <select
            aria-label="Calendario Google"
            disabled={disabled || !options.calendar_calendars.length}
            onChange={(event) => {
              const [connectionId, calendarId] = event.target.value.split("::");
              onPreferenceChange({
                calendar_connection_id: connectionId || "",
                calendar_id: calendarId || "",
              });
            }}
            value={selectedCalendar}
          >
            {!options.calendar_calendars.length && (
              <option value="::">Nessun calendario disponibile</option>
            )}
            {options.calendar_calendars.map((calendar) => (
              <option
                key={calendarValue(
                  calendar.connection_id,
                  calendar.provider_calendar_id,
                )}
                value={calendarValue(
                  calendar.connection_id,
                  calendar.provider_calendar_id,
                )}
              >
                {calendar.summary}
                {accountLabels.get(calendar.connection_id)
                  ? ` · ${accountLabels.get(calendar.connection_id)}`
                  : ""}
              </option>
            ))}
          </select>
          <div className="integration-card-actions">
            <button
              className="secondary-action"
              disabled={disabled || !canCalendar || !preferences.calendar_id}
              onClick={() => onIntegrate("calendar")}
              type="button"
            >
              {busy === "calendar"
                ? "Aggiorno…"
                : item.calendar_event.id
                  ? "Aggiorna evento"
                  : "Crea evento"}
            </button>
            {item.calendar_event.id && (
              <button
                aria-label="Apri evento nel Calendario"
                className="icon-action"
                onClick={onOpenCalendar}
                type="button"
              >
                <Icon name="external" size={15} />
              </button>
            )}
          </div>
          <small>
            {item.calendar_event.start_date
              ? `Collegato al ${item.calendar_event.start_date}`
              : "Usa la scadenza del lavoro"}
          </small>
        </article>
      </div>

      <div className="linked-documents">
        <div className="section-heading">
          <h3>Documenti</h3>
          <button
            className="secondary-action"
            disabled={disabled || !options.storage_provider_app_id}
            onClick={onPickDocument}
            type="button"
          >
            <Icon name="plus" size={15} />
            Aggiungi da Storage
          </button>
        </div>
        {item.documents.length ? (
          <div className="document-list">
            {item.documents.map((document) => (
              <article className="document-row" key={document.id}>
                <Icon name="file" size={16} />
                <button
                  className="document-name"
                  onClick={() => onOpenDocument(document)}
                  type="button"
                >
                  <strong>{document.name}</strong>
                  <small>{fileSize(document.size_bytes)}</small>
                </button>
                <button
                  aria-label={`Scollega ${document.name}`}
                  className="icon-action"
                  disabled={disabled}
                  onClick={() => onUnlinkDocument(document)}
                  type="button"
                >
                  <Icon name="close" size={14} />
                </button>
              </article>
            ))}
          </div>
        ) : (
          <p className="muted-message">
            Collega brief, contratti e materiali: saranno disponibili anche
            nella bozza Mail.
          </p>
        )}
      </div>
    </section>
  );
}
