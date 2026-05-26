import { describe, expect, it } from "vitest"

import type { Event } from "./components/ui/calendar-types"
import { applyViewState, sortEvents } from "./view-state-filtering"

function event(overrides: Partial<Event> & Pick<Event, "id" | "startTime" | "endTime" | "title">): Event {
  return {
    color: "blue",
    category: "Meeting",
    attendees: [],
    tags: [],
    ...overrides,
  }
}

describe("view state filtering", () => {
  const baseEvents: Event[] = [
    event({
      id: "evt_late",
      title: "Late review",
      startTime: new Date("2026-01-02T12:00:00Z"),
      endTime: new Date("2026-01-02T13:00:00Z"),
    }),
    event({
      id: "evt_overlap",
      title: "Planning",
      description: "Roadmap",
      location: "HQ",
      organizer: "Casey",
      startTime: new Date("2026-01-02T09:30:00Z"),
      endTime: new Date("2026-01-02T10:30:00Z"),
      attendees: ["Alice@Example.com"],
      tags: ["Team"],
    }),
    event({
      id: "evt_boundary",
      title: "Boundary",
      startTime: new Date("2026-01-02T08:00:00Z"),
      endTime: new Date("2026-01-02T09:00:00Z"),
    }),
  ]

  it("sorts events by start time without mutating the input array", () => {
    const sorted = sortEvents(baseEvents)

    expect(sorted.map((item) => item.id)).toEqual(["evt_boundary", "evt_overlap", "evt_late"])
    expect(baseEvents.map((item) => item.id)).toEqual(["evt_late", "evt_overlap", "evt_boundary"])
  })

  it("uses overlap semantics and case-insensitive attendee matching", () => {
    const visible = applyViewState(baseEvents, {
      mode: "filter",
      start_after: "2026-01-02T09:00:00Z",
      end_before: "2026-01-02T10:00:00Z",
      attendee: "alice@example.com",
    })

    expect(visible.map((item) => item.id)).toEqual(["evt_overlap"])
  })

  it("matches query text across description, location, and organizer", () => {
    const visible = applyViewState(baseEvents, { mode: "filter", query: "casey" })

    expect(visible.map((item) => item.id)).toEqual(["evt_overlap"])
  })

  it("keeps custom view order constrained to referenced events before sorting", () => {
    const visible = applyViewState(baseEvents, {
      mode: "custom",
      entity_ids: ["evt_late", "evt_missing", "evt_overlap"],
    })

    expect(visible.map((item) => item.id)).toEqual(["evt_overlap", "evt_late"])
  })

  it("filters conflicts using overlapping time and folded attendees", () => {
    const events = [
      ...baseEvents,
      event({
        id: "evt_conflict",
        title: "Conflict",
        startTime: new Date("2026-01-02T10:00:00Z"),
        endTime: new Date("2026-01-02T11:00:00Z"),
        attendees: ["ALICE@example.com"],
      }),
      event({
        id: "evt_cancelled",
        title: "Cancelled overlap",
        status: "cancelled",
        startTime: new Date("2026-01-02T09:45:00Z"),
        endTime: new Date("2026-01-02T10:15:00Z"),
        attendees: ["Alice@example.com"],
      }),
    ]

    const visible = applyViewState(events, { mode: "filter", conflicts_only: true })

    expect(visible.map((item) => item.id)).toEqual(["evt_overlap", "evt_conflict"])
  })
})
