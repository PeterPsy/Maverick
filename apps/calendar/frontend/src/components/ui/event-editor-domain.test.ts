// @vitest-environment happy-dom
import { expect, it } from "vitest";
import type { Event } from "./calendar-types";
import {
  changeDraftTimezone,
  civilDays,
  eventPatch,
  moveDraftStart,
  rebaseDraft,
  toggleAllDay,
} from "./event-editor-domain";
import { parseZonedInput, zonedInput } from "./time-layout";
import { recurrenceConfig, updateRecurrence } from "./recurrence-editor-domain";
import { validateDraft } from "./calendar-utils";
const event: Event = {
  id: "e",
  title: "Original",
  location: "Old room",
  color: "blue",
  timezone: "Europe/Rome",
  startTime: parseZonedInput("2026-10-12T09:30", "Europe/Rome"),
  endTime: parseZonedInput("2026-10-12T11:00", "Europe/Rome"),
  revision: 1,
};
it("merges independent edits and exposes only true field conflicts", () => {
  const draft = { ...event, title: "My title" },
    latest = { ...event, location: "New room", revision: 2 };
  const result = rebaseDraft(event, draft, latest, new Set(["title"]));
  expect(result.conflicts).toEqual([]);
  expect(result.draft.location).toBe("New room");
  expect(result.draft.title).toBe("My title");
  expect(
    rebaseDraft(
      event,
      draft,
      { ...latest, title: "Their title" },
      new Set(["title"]),
    ).conflicts,
  ).toEqual(["title"]);
  const patch = eventPatch(result.draft, new Set(["title"]));
  expect(patch).not.toHaveProperty("location");
  expect(patch).not.toHaveProperty("attendees");
  expect(patch.revision).toBe(2);
  expect(
    rebaseDraft(event, event, latest, new Set(["location"])).draft.location,
  ).toBe("New room");
  expect(eventPatch(event, new Set(["location"]), event)).not.toHaveProperty(
    "location",
  );
});
it("restores clock and duration after an all-day toggle, preserving a newly selected date", () => {
  const previous = { startTime: event.startTime, endTime: event.endTime };
  const allDay = { ...event, ...toggleAllDay(event, true) };
  const moved = {
    ...allDay,
    ...moveDraftStart(allDay, parseZonedInput("2026-10-13", "Europe/Rome")),
  };
  const restored = toggleAllDay(moved, false, previous);
  expect(zonedInput(restored.startTime, "Europe/Rome")).toBe(
    "2026-10-13T09:30",
  );
  expect(zonedInput(restored.endTime, "Europe/Rome")).toBe("2026-10-13T11:00");
});
it("preserves multi-day civil duration across DST when changing the first day", () => {
  const allDay = {
    ...event,
    all_day: true,
    startTime: parseZonedInput("2026-03-27", "Europe/Rome"),
    endTime: parseZonedInput("2026-03-30", "Europe/Rome"),
  };
  const moved = {
    ...allDay,
    ...moveDraftStart(allDay, parseZonedInput("2026-03-28", "Europe/Rome")),
  };
  expect(civilDays(moved)).toBe(3);
  expect(zonedInput(moved.endTime, "Europe/Rome", true)).toBe("2026-03-31");
});
it("editing recurrence preserves exclusions and changes its ending without stale count metadata", () => {
  const draft = {
    ...event,
    recurrence: {
      frequency: "weekly",
      count: 3,
      rules: [
        "RRULE:FREQ=WEEKLY;INTERVAL=2;COUNT=3;BYDAY=MO,WE",
        "EXDATE:20261014T073000Z",
      ],
      exceptions: { x: { deleted: true } },
    },
  };
  const recurrence = updateRecurrence(draft, { ending: "never", interval: 4 });
  expect(recurrence.rules).toEqual([
    "RRULE:FREQ=WEEKLY;INTERVAL=4;BYDAY=MO,WE",
    "EXDATE:20261014T073000Z",
  ]);
  expect(recurrence).not.toHaveProperty("count");
  expect(recurrenceConfig({ ...draft, recurrence }).ending).toBe("never");
  expect(recurrence).toHaveProperty("exceptions");
});

it("all-day timezone changes preserve civil dates and invalid draft inputs stay recoverable", () => {
  const draft = {
    ...event,
    all_day: true,
    startTime: parseZonedInput("2026-10-12", "Europe/Rome"),
    endTime: parseZonedInput("2026-10-14", "Europe/Rome"),
  };
  const changed = changeDraftTimezone(draft, "America/New_York");
  expect(zonedInput(changed.startTime, "America/New_York", true)).toBe(
    "2026-10-12",
  );
  expect(zonedInput(changed.endTime, "America/New_York", true)).toBe(
    "2026-10-14",
  );
  expect(civilDays({ ...draft, endTime: new Date(NaN) })).toBe(1);
  expect(() =>
    toggleAllDay({ ...event, startTime: new Date(NaN) }, true),
  ).not.toThrow();
});

it("all-day recurrence endings use civil dates and non-weekly BYDAY stays advanced", () => {
  const recurrence = updateRecurrence(
    { ...event, all_day: true, recurrence: { frequency: "daily" } },
    { ending: "until", until: "2026-10-14" },
  );
  expect(recurrence.rules).toEqual([
    "RRULE:FREQ=DAILY;INTERVAL=1;UNTIL=20261014",
  ]);
  expect(
    recurrenceConfig({
      ...event,
      recurrence: { rules: ["RRULE:FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR"] },
    }).custom,
  ).toBe(true);
});

it("rejects invalid reminder offsets before a provider write can omit them", () => {
  expect(
    validateDraft({
      ...event,
      reminders: [{ method: "popup", minutes_before: 3.5 }],
    }),
  ).toContain("whole number");
  expect(
    validateDraft({
      ...event,
      reminders: [
        { method: "popup", minutes_before: 10 },
        { method: "email", minutes_before: 60 },
      ],
    }),
  ).toBe("");
});
