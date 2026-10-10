import type { DraftEvent, Event } from "./calendar-types";
import { parseZonedInput, zonedInput } from "./time-layout";

export const editableFields = [
  "title",
  "description",
  "startTime",
  "endTime",
  "status",
  "transparency",
  "timezone",
  "location",
  "all_day",
  "color",
  "category",
  "attendees",
  "attendee_details",
  "tags",
  "source",
  "external_refs",
  "recurrence",
  "reminders",
  "reminders_use_default",
] as const;
export type EditableField = (typeof editableFields)[number];
function value(event: DraftEvent, key: EditableField) {
  if (key === "external_refs") {
    const refs = event.external_refs || {};
    return JSON.stringify([
      refs.calendar_connection_id,
      refs.provider_calendar_id,
    ]);
  }
  return JSON.stringify(event[key]);
}
export function rebaseDraft(
  base: Event,
  draft: Event,
  latest: Event,
  changed: Set<string>,
) {
  const edited = editableFields.filter(
    (key) => changed.has(key) && value(base, key) !== value(draft, key),
  );
  const conflicts = edited.filter(
    (key) =>
      changed.has(key) &&
      value(base, key) !== value(latest, key) &&
      value(draft, key) !== value(latest, key),
  );
  const patch = Object.fromEntries(edited.map((key) => [key, draft[key]]));
  const merged = { ...latest, ...patch, revision: latest.revision } as Event;
  if (edited.includes("external_refs"))
    merged.external_refs = {
      ...latest.external_refs,
      ...draft.external_refs,
      etag: latest.external_refs?.etag,
    };
  return { draft: merged, conflicts };
}
export function eventPatch(
  draft: Event,
  changed: Set<string>,
  base?: Event | null,
): Partial<Event> {
  return {
    ...Object.fromEntries(
      editableFields
        .filter(
          (key) =>
            changed.has(key) &&
            (!base || value(base, key) !== value(draft, key)),
        )
        .map((key) => [key, draft[key]]),
    ),
    revision: draft.revision,
    external_refs: draft.external_refs,
    source: draft.source,
    recurrence_scope: draft.recurrence_scope || "occurrence",
  };
}
export function civilDays(draft: DraftEvent) {
  const zone = draft.timezone || "UTC";
  if (
    !draft.startTime ||
    !draft.endTime ||
    !Number.isFinite(draft.startTime.getTime()) ||
    !Number.isFinite(draft.endTime.getTime())
  )
    return 1;
  return Math.max(
    1,
    Math.round(
      (Date.parse(zonedInput(draft.endTime, zone, true)) -
        Date.parse(zonedInput(draft.startTime, zone, true))) /
        86400000,
    ),
  );
}
export function shiftCivilDate(value: string, days: number) {
  const date = new Date(`${value}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}
export function toggleAllDay(
  draft: DraftEvent,
  allDay: boolean,
  previous?: { startTime: Date; endTime: Date },
): DraftEvent {
  const zone =
    draft.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (
    !allDay &&
    previous &&
    Number.isFinite(previous.startTime.getTime()) &&
    Number.isFinite(previous.endTime.getTime())
  ) {
    const day = zonedInput(draft.startTime, zone, true);
    const clock = zonedInput(previous.startTime, zone).slice(11);
    const startTime = parseZonedInput(`${day}T${clock}`, zone);
    return {
      all_day: false,
      startTime,
      endTime: new Date(
        startTime.getTime() +
          previous.endTime.getTime() -
          previous.startTime.getTime(),
      ),
    };
  }
  const day = zonedInput(
    draft.startTime && Number.isFinite(draft.startTime.getTime())
      ? draft.startTime
      : new Date(),
    zone,
    true,
  );
  return allDay
    ? {
        all_day: true,
        timezone: zone,
        startTime: parseZonedInput(day, zone),
        endTime: parseZonedInput(shiftCivilDate(day, 1), zone),
      }
    : {
        all_day: false,
        startTime: parseZonedInput(`${day}T09:00`, zone),
        endTime: parseZonedInput(`${day}T10:00`, zone),
      };
}
export function moveDraftStart(draft: DraftEvent, startTime: Date): DraftEvent {
  if (
    !draft.startTime ||
    !draft.endTime ||
    !Number.isFinite(draft.startTime.getTime()) ||
    !Number.isFinite(draft.endTime.getTime()) ||
    !Number.isFinite(startTime.getTime())
  )
    return { startTime };
  const zone = draft.timezone || "UTC";
  return {
    startTime,
    endTime: draft.all_day
      ? parseZonedInput(
          shiftCivilDate(zonedInput(startTime, zone, true), civilDays(draft)),
          zone,
        )
      : new Date(
          startTime.getTime() +
            draft.endTime.getTime() -
            draft.startTime.getTime(),
        ),
  };
}
export function changeDraftTimezone(
  draft: DraftEvent,
  timezone: string,
): DraftEvent {
  const previous =
    draft.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (!draft.all_day) return { timezone };
  return {
    timezone,
    ...(draft.startTime && Number.isFinite(draft.startTime.getTime())
      ? {
          startTime: parseZonedInput(
            zonedInput(draft.startTime, previous, true),
            timezone,
          ),
        }
      : {}),
    ...(draft.endTime && Number.isFinite(draft.endTime.getTime())
      ? {
          endTime: parseZonedInput(
            zonedInput(draft.endTime, previous, true),
            timezone,
          ),
        }
      : {}),
  };
}
export function safeLink(value: unknown, allowPhone = false) {
  try {
    const url = new URL(String(value));
    return url.protocol === "https:" ||
      url.protocol === "http:" ||
      (allowPhone && url.protocol === "tel:")
      ? url.href
      : "";
  } catch {
    return "";
  }
}
