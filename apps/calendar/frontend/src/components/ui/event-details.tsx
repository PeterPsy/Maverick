import { t, readPreferences } from "@/preferences";
import type {
  Event,
  CalendarConnection,
  CalendarRemoteCalendar,
} from "./calendar-types";
import { eventSourceDetails } from "./calendar-utils";
import { civilDays, safeLink, shiftCivilDate } from "./event-editor-domain";
import { zonedInput } from "./time-layout";
import { recurrenceSummary } from "./event-recurrence";
import { responseLabel } from "./event-people";
import { EventDescription } from "./event-description";

export function eventWhen(event: Event) {
  const prefs = readPreferences();
  const zone =
    event.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (event.all_day) {
    const format = (date: string) =>
      new Intl.DateTimeFormat(prefs.locale, {
        dateStyle: "long",
        timeZone: "UTC",
      }).format(new Date(`${date}T12:00:00Z`));
    const start = zonedInput(event.startTime, zone, true),
      end = shiftCivilDate(zonedInput(event.endTime, zone, true), -1);
    return `${format(start)}${start === end ? "" : ` – ${format(end)}`} · ${t("All day")}`;
  }
  const format = new Intl.DateTimeFormat(prefs.locale, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: zone,
    hour12: prefs.hour12,
  });
  return `${format.format(event.startTime)} – ${format.format(event.endTime)}`;
}
export function EventDetails({
  event,
  connections,
  calendars,
  readOnly,
}: {
  event: Event;
  connections: CalendarConnection[];
  calendars: CalendarRemoteCalendar[];
  readOnly: boolean;
}) {
  const source = eventSourceDetails(event, connections);
  const calendar = calendars.find(
    (c) =>
      c.connection_id === source.connectionId &&
      c.provider_calendar_id === source.providerCalendarId,
  );
  const connection = connections.find((c) => c.id === source.connectionId);
  const synced =
    calendar?.sync_status?.last_sync_at || connection?.last_sync_at;
  const stale =
    connection?.sync_status?.stale ||
    !synced ||
    Date.now() - Date.parse(synced) > 86400000;
  const google = event.source === "google_calendar";
  const open = safeLink(
    event.external_refs?.html_link || event.external_refs?.htmlLink,
  );
  const reminders = (event.reminders || []) as Array<{
    method: string;
    minutes_before: number;
  }>;
  return (
    <div className="calendar-event-reading">
      <h2>{event.title}</h2>
      <p className="calendar-event-when">{eventWhen(event)}</p>
      <p>
        {event.all_day
          ? `${civilDays(event)} ${t("days")}`
          : `${Math.round((event.endTime.getTime() - event.startTime.getTime()) / 60000)} ${t("minutes")}`}{" "}
        · {event.timezone || "UTC"}
      </p>
      <div className="calendar-event-badges">
        <span>{source.calendarName || t("Local calendar")}</span>
        {source.accountName && <span>{source.accountName}</span>}
        <span>{t(readOnly ? "Read only" : "Editable")}</span>
        <span>{t(event.transparency === "transparent" ? "Free" : "Busy")}</span>
        <span>
          {t(
            event.status === "tentative"
              ? "Tentative"
              : event.status === "cancelled"
                ? "Cancelled"
                : "Confirmed",
          )}
        </span>
      </div>
      {google && (
        <p className={stale ? "calendar-notice" : ""}>
          {stale && `${t("Data needs updating")} · `}
          {synced
            ? `${t("Last sync")}: ${new Date(synced).toLocaleString(readPreferences().locale)}`
            : t("Never synced")}
          {calendar?.sync_status?.status === "partial" &&
            ` · ${t("Partial sync")}`}
        </p>
      )}
      {readOnly && (
        <p>
          {t("This connected account has read-only access to the calendar.")}
        </p>
      )}
      <div className="calendar-event-links">
        {open && (
          <a href={open} target="_blank" rel="noopener noreferrer">
            {t("Open in Google Calendar")}
          </a>
        )}
        {event.conference?.entry_points?.map(
          (point) =>
            safeLink(point.uri, true) && (
              <a
                key={point.uri}
                href={safeLink(point.uri, true)}
                target="_blank"
                rel="noopener noreferrer"
              >
                {point.type === "video"
                  ? t("Join call")
                  : point.label ||
                    event.conference?.provider ||
                    t("Conference")}
              </a>
            ),
        )}
      </div>
      {event.location && (
        <section>
          <h3>{t("Location")}</h3>
          <p>{event.location}</p>
          <a
            href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(event.location)}`}
            target="_blank"
            rel="noopener noreferrer"
          >
            {t("Open map")}
          </a>
        </section>
      )}
      {Boolean(event.organizer || event.attendees?.length) && (
        <section>
          <h3>{t("Attendees")}</h3>
          {event.organizer && (
            <p>
              {t("Organizer")}: {event.organizer}
            </p>
          )}
          <ul className="calendar-people-list">
            {event.attendees?.map((email) => {
              const person = event.attendee_details?.find(
                (p) => p.email.toLowerCase() === email.toLowerCase(),
              );
              return (
                <li key={email}>
                  <div>
                    <strong>{person?.displayName || email}</strong>
                    {person?.displayName && <span>{email}</span>}
                    {google && (
                      <small>
                        {responseLabel(person?.responseStatus)}
                        {person?.optional && ` · ${t("Optional")}`}
                      </small>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      )}
      {event.description && (
        <section>
          <h3>{t("Description")}</h3>
          <EventDescription text={event.description} />
        </section>
      )}
      {(Object.keys(event.recurrence || {}).length > 0 ||
        event.series_id ||
        Boolean(event.external_refs?.recurring_event_id)) && (
        <section>
          <h3>{t("Recurrence")}</h3>
          <p>{recurrenceSummary(event)}</p>
        </section>
      )}
      <section>
        <h3>{t("Reminders")}</h3>
        {google && event.reminders_use_default !== false ? (
          <p>{t("Use Google default reminders")}</p>
        ) : reminders.length ? (
          <ul>
            {reminders.map((r, i) => (
              <li key={i}>
                {r.minutes_before} {t("minutes before")} ·{" "}
                {r.method === "email" ? "Email" : t("Notification")}
              </li>
            ))}
          </ul>
        ) : (
          <p>{t("No reminders")}</p>
        )}
      </section>
      {(event.tags?.length || event.category) && (
        <details>
          <summary>{t("Classification")}</summary>
          <p>{event.category}</p>
          <p>{event.tags?.join(" · ")}</p>
        </details>
      )}
    </div>
  );
}
