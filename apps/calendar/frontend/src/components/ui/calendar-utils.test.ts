import { describe, expect, it } from "vitest"

import type { Event } from "./calendar-types"
import {
  calendarAccountFilterValues,
  calendarAccountOptions,
  calendarAccountValue,
  calendarSourceOptions,
  calendarSourcePatch,
  eventIsReadOnly,
  eventsForListDate,
  eventSourceDetails,
  isWritableGoogleAccessRole,
  selectedCalendarSourceValue,
  validateDraft,
  viewportFromViewState,
  viewStateSignature,
} from "./calendar-utils"

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

  it("keeps list views anchored to the selected date", () => {
    expect(eventsForListDate(events, new Date("2026-01-04T12:00:00Z")).map((item) => item.id)).toEqual(["evt_2"])
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
      { name: "Ana Work", value: "ana@example.com", accountId: "ana@example.com" },
      { name: "Calendar", value: "calendar" },
    ])
  })

  it("prefers backend calendar connections while keeping event fallback accounts", () => {
    const accountEvents = [
      event({
        id: "evt_google",
        title: "Google",
        startTime: new Date("2026-01-03T09:00:00Z"),
        endTime: new Date("2026-01-03T10:00:00Z"),
        source: "google_calendar",
        external_refs: {
          calendar_account_id: "ana@example.com",
          calendar_account_label: "Ana Work",
          calendar_connection_id: "cal_conn_work",
        },
      }),
    ]

    expect(calendarAccountOptions(accountEvents, [
      { id: "cal_conn_work", provider: "google", account_id: "ana@example.com", account_label: "Ana Work", status: "connected" },
      { id: "cal_conn_empty", provider: "google", account_id: "empty@example.com", account_label: "Empty", status: "connected" },
    ])).toEqual([
      { name: "Ana Work", value: "cal_conn_work", accountId: "ana@example.com", connectionId: "cal_conn_work", provider: "google", status: "connected" },
      { name: "Empty", value: "cal_conn_empty", accountId: "empty@example.com", connectionId: "cal_conn_empty", provider: "google", status: "connected" },
    ])
    expect(calendarAccountFilterValues(accountEvents[0])).toContain("cal_conn_work")
  })

  it("builds source choices and preserves non-calendar refs when changing source", () => {
    const googleEvent = event({
      id: "evt_google",
      title: "Google",
      startTime: new Date("2026-01-03T09:00:00Z"),
      endTime: new Date("2026-01-03T10:00:00Z"),
      source: "google_calendar",
      external_refs: {
        crm_deal: "deal_123",
        calendar_account_id: "ana@example.com",
        calendar_account_label: "Ana Work",
        calendar_connection_id: "cal_conn_work",
        provider_calendar_id: "primary",
        provider_calendar_summary: "Work",
        html_link: "https://calendar.google.com/event?eid=abc",
      },
    })
    const connections = [
      { id: "cal_conn_work", provider: "google", account_id: "ana@example.com", account_label: "Ana Work", status: "connected" },
    ]
    const options = calendarSourceOptions([googleEvent], connections)

    expect(options.map((option) => option.value)).toEqual(["local", "connection:cal_conn_work"])
    expect(options.find((option) => option.value === "connection:cal_conn_work")).toMatchObject({
      source: "google_calendar",
      providerCalendarId: "primary",
      externalRefs: {
        calendar_connection_id: "cal_conn_work",
        provider_calendar_id: "primary",
      },
    })
    expect(selectedCalendarSourceValue(googleEvent, options)).toBe("connection:cal_conn_work")
    expect(eventSourceDetails(googleEvent).remoteLink).toBe("https://calendar.google.com/event?eid=abc")
    expect(calendarSourcePatch(googleEvent, "local", options)).toEqual({
      source: "calendar",
      external_refs: { crm_deal: "deal_123" },
    })

    const withEmptyCalendar = calendarSourceOptions([], connections, [
      {
        id: "cal_conn_work:empty@example.com",
        connection_id: "cal_conn_work",
        provider: "google",
        provider_calendar_id: "empty@example.com",
        summary: "Empty",
        sync_enabled: false,
      },
    ])
    expect(withEmptyCalendar.map((option) => option.value)).toEqual([
      "local",
      "calendar:cal_conn_work:empty@example.com",
    ])
    expect(withEmptyCalendar[1]).toMatchObject({
      name: "Ana Work / Empty",
      providerCalendarId: "empty@example.com",
      writable: true,
      externalRefs: {
        calendar_connection_id: "cal_conn_work",
        provider_calendar_id: "empty@example.com",
      },
    })
  })

  it("marks Google reader calendars and events as non-writable", () => {
    expect(isWritableGoogleAccessRole("owner")).toBe(true)
    expect(isWritableGoogleAccessRole("writer")).toBe(true)
    expect(isWritableGoogleAccessRole("reader")).toBe(false)

    const connections = [
      { id: "cal_conn_work", provider: "google", account_id: "ana@example.com", account_label: "Ana Work", status: "connected" },
    ]
    const calendars = [
      {
        id: "cal_conn_work:primary",
        connection_id: "cal_conn_work",
        provider: "google",
        provider_calendar_id: "primary",
        summary: "Work",
        access_role: "reader",
      },
      {
        id: "cal_conn_work:team@example.com",
        connection_id: "cal_conn_work",
        provider: "google",
        provider_calendar_id: "team@example.com",
        summary: "Team",
        access_role: "writer",
      },
    ]
    const readOnlyEvent = event({
      id: "evt_google_readonly",
      title: "Google",
      startTime: new Date("2026-01-03T09:00:00Z"),
      endTime: new Date("2026-01-03T10:00:00Z"),
      source: "google_calendar",
      external_refs: {
        calendar_connection_id: "cal_conn_work",
        provider_calendar_id: "primary",
      },
    })

    const options = calendarSourceOptions([readOnlyEvent], connections, calendars)
    expect(options.find((option) => option.value === "connection:cal_conn_work")).toBeUndefined()
    expect(options.find((option) => option.value === "calendar:cal_conn_work:primary")).toMatchObject({ writable: false })
    expect(options.find((option) => option.value === "calendar:cal_conn_work:team@example.com")).toMatchObject({ writable: true })
    expect(eventIsReadOnly(readOnlyEvent, calendars)).toBe(true)
  })
})
