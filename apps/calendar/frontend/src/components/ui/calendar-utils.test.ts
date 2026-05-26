import { describe, expect, it } from "vitest"

import type { Event } from "./calendar-types"
import { calendarAccountOptions, calendarAccountValue, validateDraft, viewportFromViewState, viewStateSignature } from "./calendar-utils"

function event(overrides: Partial<Event> & Pick<Event, "id" | "startTime" | "endTime" | "title">): Event {
  return {
    color: "blue",
    category: "Meeting",
    attendees: [],
    tags: [],
    ...overrides,
  }
}

describe("calendar viewport helpers", () => {
  const events = [
    event({
      id: "evt_1",
      title: "Focus",
      startTime: new Date("2026-01-03T09:00:00Z"),
      endTime: new Date("2026-01-03T10:00:00Z"),
    }),
    event({
      id: "evt_2",
      title: "Second",
      startTime: new Date("2026-01-04T09:00:00Z"),
      endTime: new Date("2026-01-04T10:00:00Z"),
    }),
  ]

  it("chooses an event-centered viewport for custom views", () => {
    expect(viewportFromViewState({ mode: "custom", entity_ids: ["evt_2"] }, events, "month")).toMatchObject({
      date: events[1].startTime,
      view: "day",
    })
    expect(viewportFromViewState({ mode: "custom", entity_ids: ["evt_1", "evt_2"] }, events, "month")).toMatchObject({
      date: events[0].startTime,
      view: "list",
    })
  })

  it("marks unresolved custom views as pending while events are still loading", () => {
    expect(viewportFromViewState({ mode: "custom", entity_ids: ["evt_missing"] }, [], "month")).toMatchObject({
      view: "list",
      pendingEventResolution: true,
    })
  })

  it("selects the compact view for bounded filter windows", () => {
    expect(
      viewportFromViewState(
        {
          mode: "filter",
          start_after: "2026-01-03T00:00:00Z",
          end_before: "2026-01-03T23:59:00Z",
        },
        events,
        "month",
      ),
    ).toMatchObject({ view: "day" })

    expect(
      viewportFromViewState(
        {
          mode: "filter",
          start_after: "2026-01-01T00:00:00Z",
          end_before: "2026-01-08T00:00:00Z",
        },
        events,
        "month",
      ),
    ).toMatchObject({ view: "week" })
  })

  it("builds stable signatures from normalized view-state fields", () => {
    expect(
      viewStateSignature({
        mode: " filter ",
        query: " roadmap ",
        tags: [" Team ", ""],
        entity_ids: [" evt_1 "],
        conflicts_only: 1 as unknown as boolean,
      }),
    ).toBe(
      JSON.stringify({
        mode: "filter",
        query: "roadmap",
        start_after: "",
        end_before: "",
        category: "",
        attendee: "",
        tags: ["Team"],
        conflicts_only: true,
        entity_ids: ["evt_1"],
      }),
    )
  })

  it("validates event drafts before persistence", () => {
    expect(validateDraft({ title: "", startTime: new Date(), endTime: new Date(Date.now() + 60000) })).toBe(
      "Title is required.",
    )
    expect(validateDraft({ title: "Invalid", startTime: new Date("x"), endTime: new Date() })).toBe(
      "Start time is required.",
    )
    expect(
      validateDraft({
        title: "Backwards",
        startTime: new Date("2026-01-03T10:00:00Z"),
        endTime: new Date("2026-01-03T09:00:00Z"),
      }),
    ).toBe("End time must be after start time.")
  })

  it("builds calendar account filter options from event sources", () => {
    const accountEvents = [
      event({
        id: "evt_google",
        title: "Google",
        startTime: new Date("2026-01-03T09:00:00Z"),
        endTime: new Date("2026-01-03T10:00:00Z"),
        source: "google_work",
        external_refs: { calendar_account_id: "ana@example.com", calendar_account_label: "Ana Work" },
      }),
      event({
        id: "evt_default",
        title: "Default",
        startTime: new Date("2026-01-03T11:00:00Z"),
        endTime: new Date("2026-01-03T12:00:00Z"),
      }),
      event({
        id: "evt_duplicate",
        title: "Duplicate",
        startTime: new Date("2026-01-03T13:00:00Z"),
        endTime: new Date("2026-01-03T14:00:00Z"),
        external_refs: { calendar_account_id: "ana@example.com" },
      }),
    ]

    expect(calendarAccountValue(accountEvents[1])).toBe("calendar")
    expect(calendarAccountOptions(accountEvents)).toEqual([
      { name: "Ana Work", value: "ana@example.com" },
      { name: "Calendar", value: "calendar" },
    ])
  })
})
