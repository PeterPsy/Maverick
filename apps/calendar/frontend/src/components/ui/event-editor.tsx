import { t } from "@/preferences";
import { Input } from "./input";
import { Textarea } from "./textarea";
import { Field } from "./event-panel-fields";
import {
  calendarSourcePatch,
  selectedCalendarSourceValue,
} from "./calendar-utils";
import { EventSchedule } from "./event-schedule";
import { EventClassification } from "./event-classification";
import { EventPeople } from "./event-people";
import { EventReminders } from "./event-reminders";
import { EventRecurrence } from "./event-recurrence";
import type { EventPanelProps } from "./event-panel-types";
export function EventEditor(
  props: EventPanelProps & { draft: NonNullable<EventPanelProps["draft"]> },
) {
  const draft = props.draft;
  const remoteConnection = draft?.external_refs?.provider_event_id
    ? draft.external_refs.calendar_connection_id
    : undefined;
  const recurring = !!(
    draft?.series_id || draft?.external_refs?.recurring_event_id
  );
  const sources = (props.calendarSourceOptions || []).filter(
    (option) =>
      option.writable !== false &&
      (!remoteConnection || option.connectionId === remoteConnection) &&
      (!recurring ||
        draft?.recurrence_scope === "series" ||
        option.providerCalendarId ===
          draft?.external_refs?.provider_calendar_id),
  );
  return (
    <fieldset
      className="calendar-event-panel__body calendar-event-editor"
      disabled={props.isSaving}
    >
      <Field label="Title">
        <Input
          value={draft.title || ""}
          maxLength={160}
          onChange={(e) => props.setDraft({ title: e.target.value })}
          placeholder={t("Event title")}
        />
      </Field>
      {sources.length > 1 ? (
        <Field label="Calendar">
          <select
            value={selectedCalendarSourceValue(draft, sources)}
            disabled={!props.canSave}
            onChange={(e) =>
              props.setDraft(
                calendarSourcePatch(draft, e.target.value, sources),
              )
            }
          >
            {sources.map((option) => (
              <option key={option.value} value={option.value}>
                {option.name}
              </option>
            ))}
          </select>
        </Field>
      ) : (
        <p>{sources[0]?.name || t("Local calendar")}</p>
      )}
      <EventSchedule {...props} draft={draft} />
      <Field label="Location">
        <Input
          value={draft.location || ""}
          maxLength={240}
          onChange={(e) => props.setDraft({ location: e.target.value })}
        />
      </Field>
      <details open={Boolean(draft.attendees?.length)}>
        <summary>
          {t("Attendees")}
          {draft.attendees?.length ? ` (${draft.attendees.length})` : ""}
        </summary>
        <EventPeople draft={draft} onChange={props.setDraft} />
      </details>
      <Field label="Description">
        <Textarea
          rows={5}
          maxLength={5000}
          value={draft.description || ""}
          onChange={(e) => props.setDraft({ description: e.target.value })}
        />
      </Field>
      <EventReminders draft={draft} onChange={props.setDraft} />
      <details
        open={Boolean(recurring || Object.keys(draft.recurrence || {}).length)}
      >
        <summary>{t("Recurrence")}</summary>
        <EventRecurrence draft={draft} onChange={props.setDraft} />
      </details>
      {recurring &&
        Boolean(remoteConnection) &&
        draft.recurrence_scope !== "series" && (
          <p>{t("Select entire series to transfer this recurring event.")}</p>
        )}
      <EventClassification {...props} draft={draft} />
      {props.children}
    </fieldset>
  );
}
