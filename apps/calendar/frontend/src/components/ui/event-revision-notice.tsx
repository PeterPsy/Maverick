import { t, readPreferences } from "@/preferences";
import type { Event } from "./calendar-types";
import type { EditableField } from "./event-editor-domain";
import { eventSourceDetails } from "./calendar-utils";
import { recurrenceSummary } from "./event-recurrence";
const labels: Partial<Record<EditableField, string>> = {
  title: "Title",
  description: "Description",
  location: "Location",
  startTime: "Start Time",
  endTime: "End Time",
  timezone: "Timezone",
  attendees: "Attendees",
  attendee_details: "Attendees",
  recurrence: "Recurrence",
  reminders: "Reminders",
  reminders_use_default: "Reminders",
  category: "Category",
  tags: "Tags",
  external_refs: "Calendar",
  source: "Calendar",
  all_day: "All day",
  status: "Status",
  transparency: "Busy",
  color: "Color",
};
function display(event: Event, field: EditableField): string {
  if (field === "recurrence") return recurrenceSummary(event);
  if (field === "external_refs" || field === "source") {
    const source = eventSourceDetails(event);
    return (
      [source.accountName, source.calendarName].filter(Boolean).join(" / ") ||
      t("Local calendar")
    );
  }
  if (field === "attendee_details")
    return (event.attendee_details || [])
      .map(
        (p) =>
          `${p.displayName || p.email}${p.optional ? ` (${t("Optional")})` : ""}`,
      )
      .join(", ");
  if (field === "reminders")
    return (
      (event.reminders as { method: string; minutes_before: number }[]) || []
    )
      .map(
        (r) =>
          `${r.minutes_before} ${t("minutes before")} · ${r.method === "email" ? "Email" : t("Notification")}`,
      )
      .join(", ");
  const value = event[field];
  if (value instanceof Date)
    return value.toLocaleString(readPreferences().locale, {
      timeZone: event.timezone || "UTC",
    });
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "boolean") return t(value ? "Yes" : "No");
  return String(value || "—");
}
export function EventRevisionNotice({
  draft,
  latest,
  fields,
  disabled,
  onMerge,
  onReload,
}: {
  draft: Event | null;
  latest: Event | null;
  fields: EditableField[];
  disabled: boolean;
  onMerge: () => void;
  onReload: () => void;
}) {
  return (
    <div className="calendar-notice" role="alert">
      <p>{t("Another version is available. Your draft has been kept.")}</p>
      {draft &&
        latest &&
        fields.map((field) => (
          <div className="calendar-field-conflict" key={field}>
            <strong>{t(labels[field] || field)}</strong>
            <p>
              {t("Your draft")}: {display(draft, field)}
            </p>
            <p>
              {t("Current version")}: {display(latest, field)}
            </p>
          </div>
        ))}
      <button type="button" disabled={disabled} onClick={onMerge}>
        {t(
          fields.length
            ? "Use my changes for conflicting fields"
            : "Merge my changes with latest version",
        )}
      </button>
      <button type="button" disabled={disabled} onClick={onReload}>
        {t("Reload latest event")}
      </button>
    </div>
  );
}
