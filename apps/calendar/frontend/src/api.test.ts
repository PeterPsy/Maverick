import { afterEach, describe, expect, it, vi } from "vitest"

import {
  CalendarApiError,
  completeGoogleOAuth,
  createEvent,
  deleteEvent,
  listConnections,
  listCalendars,
  listEvents,
  readViewFilter,
  selectCalendar,
  startGoogleOAuth,
  syncCalendar,
  updateEvent,
} from "./api"

describe("Calendar API OAuth helpers", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("starts Google OAuth with an explicit client-id secret request but no secret values", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        action: "calendar_connections.start_oauth",
        provider: "google",
        authorization_url: "https://accounts.google.com/o/oauth2/v2/auth?state=opaque",
        state: "opaque",
        connection: { id: "cal_conn_1", provider: "google", status: "pending" },
      }),
    )
    vi.stubGlobal("fetch", fetchMock)

    const result = await startGoogleOAuth("calendar", { redirectUri: "https://maverick.example/apps/calendar/oauth/callback" })
    const body = requestBody(fetchMock)

    expect(result.authorization_url).toContain("accounts.google.com")
    expect(body).toEqual({
      action: "calendar_connections.start_oauth",
      provider: "google",
      redirect_uri: "https://maverick.example/apps/calendar/oauth/callback",
      _app_secret_request: {
        required: true,
        selectors: [
          {
            logical_names: ["google-oauth-client-id"],
          },
        ],
      },
    })
    expect(JSON.stringify(body)).not.toMatch(/client_secret|refresh_token/i)
  })

  it("completes Google OAuth with explicit OAuth credential selectors but no secret values", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        action: "calendar_connections.complete_oauth",
        provider: "google",
        connection: { id: "cal_conn_1", provider: "google", status: "connected", account_label: "Work" },
      }),
    )
    vi.stubGlobal("fetch", fetchMock)

    const result = await completeGoogleOAuth("calendar", {
      code: "oauth-code",
      state: "opaque-state",
      redirectUri: "https://maverick.example/apps/calendar/oauth/callback",
    })
    const body = requestBody(fetchMock)

    expect(result.connection.status).toBe("connected")
    expect(body).toEqual({
      action: "calendar_connections.complete_oauth",
      provider: "google",
      code: "oauth-code",
      state: "opaque-state",
      redirect_uri: "https://maverick.example/apps/calendar/oauth/callback",
      _app_secret_request: {
        required: true,
        selectors: [
          {
            logical_names: ["google-oauth-client-id", "google-oauth-client-secret"],
          },
        ],
      },
    })
    expect(JSON.stringify(body)).not.toMatch(/client_secret|refresh_token|oauth-code-secret/i)
  })

  it("syncs Google Calendar with the refresh token scoped to the connection resource", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        action: "calendar_sync",
        provider: "google",
        connection_id: "cal_conn_1",
        synced: true,
      }),
    )
    vi.stubGlobal("fetch", fetchMock)

    const result = await syncCalendar("calendar", "cal_conn_1", { calendarId: "primary", fullSync: true })
    const body = requestBody(fetchMock)

    expect(result.synced).toBe(true)
    expect(body).toEqual({
      action: "calendar_sync",
      connection_id: "cal_conn_1",
      calendar_id: "primary",
      full_sync: true,
      _app_secret_request: {
        required: true,
        selectors: [
          {
            logical_names: ["google-oauth-client-id", "google-oauth-client-secret"],
          },
          {
            logical_names: ["google-calendar-refresh-token"],
            resource_type: "calendar_connection",
            resource_id: "cal_conn_1",
          },
        ],
      },
    })
  })

  it("lists and selects remote calendars without secret values", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          action: "calendar_calendars.list",
          calendars: [
            {
              id: "cal_conn_1:primary",
              connection_id: "cal_conn_1",
              provider: "google",
              provider_calendar_id: "primary",
              summary: "Work",
              sync_enabled: true,
            },
          ],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          action: "calendar_calendars.select",
          calendar: {
            id: "cal_conn_1:primary",
            connection_id: "cal_conn_1",
            provider: "google",
            provider_calendar_id: "primary",
            summary: "Work",
            sync_enabled: false,
          },
        }),
      )
    vi.stubGlobal("fetch", fetchMock)

    const calendars = await listCalendars("calendar", "cal_conn_1")
    const selected = await selectCalendar("calendar", "cal_conn_1", "primary", { syncEnabled: false })

    expect(calendars[0].summary).toBe("Work")
    expect(selected.sync_enabled).toBe(false)
    expect(requestBodyAt(fetchMock, 0)).toEqual({
      action: "calendar_calendars.list",
      connection_id: "cal_conn_1",
      _app_secret_request: noSecretRequest(),
    })
    expect(requestBodyAt(fetchMock, 1)).toEqual({
      action: "calendar_calendars.select",
      connection_id: "cal_conn_1",
      calendar_id: "primary",
      sync_enabled: false,
      _app_secret_request: noSecretRequest(),
    })
    expect(JSON.stringify(requestBodyAt(fetchMock, 1))).not.toMatch(/client_secret|refresh_token/i)
  })

  it("declares no secret delivery for local read calls", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ action: "list", events: [] }))
      .mockResolvedValueOnce(jsonResponse({ action: "view_filter", view_state: {} }))
      .mockResolvedValueOnce(jsonResponse({ action: "calendar_connections.list", connections: [] }))
    vi.stubGlobal("fetch", fetchMock)

    await listEvents("calendar")
    await readViewFilter("calendar")
    await listConnections("calendar")

    expect(requestBodyAt(fetchMock, 0)).toEqual({ action: "list", _app_secret_request: noSecretRequest() })
    expect(requestBodyAt(fetchMock, 1)).toEqual({ action: "view_filter", _app_secret_request: noSecretRequest() })
    expect(requestBodyAt(fetchMock, 2)).toEqual({ action: "calendar_connections.list", _app_secret_request: noSecretRequest() })
  })

  it("creates Google-backed events with resource-scoped mutation secrets", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        action: "create",
        event: googleEventPayload("evt_1"),
      }),
    )
    vi.stubGlobal("fetch", fetchMock)

    await createEvent("calendar", googleEvent("evt_1"))
    const body = requestBody(fetchMock)

    expect(body._app_secret_request).toEqual(googleMutationSecretRequest("cal_conn_1"))
    expect(JSON.stringify(body)).not.toMatch(/client_secret|refresh_token/i)
  })

  it("updates Google-backed events with resource-scoped mutation secrets", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        action: "update",
        event: googleEventPayload("evt_1"),
      }),
    )
    vi.stubGlobal("fetch", fetchMock)

    await updateEvent("calendar", "evt_1", googleEvent("evt_1"))
    const body = requestBody(fetchMock)

    expect(body._app_secret_request).toEqual(googleMutationSecretRequest("cal_conn_1"))
    expect(body.expected_revision).toBe(1)
  })

  it("deletes Google-backed events with resource-scoped mutation secrets", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ action: "delete", deleted: true }))
    vi.stubGlobal("fetch", fetchMock)

    await deleteEvent("calendar", "evt_1", 1, googleEvent("evt_1"))
    const body = requestBody(fetchMock)

    expect(body._app_secret_request).toEqual(googleMutationSecretRequest("cal_conn_1"))
    expect(body.expected_revision).toBe(1)
  })

  it("declares no secret delivery for local event mutations", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ action: "create", event: localEventPayload("evt_1") }))
      .mockResolvedValueOnce(jsonResponse({ action: "update", event: localEventPayload("evt_1") }))
      .mockResolvedValueOnce(jsonResponse({ action: "delete", deleted: true }))
    vi.stubGlobal("fetch", fetchMock)

    await createEvent("calendar", localEvent("evt_1"))
    await updateEvent("calendar", "evt_1", localEvent("evt_1"))
    await deleteEvent("calendar", "evt_1", 1, localEvent("evt_1"))

    expect(requestBodyAt(fetchMock, 0)._app_secret_request).toEqual(noSecretRequest())
    expect(requestBodyAt(fetchMock, 1)._app_secret_request).toEqual(noSecretRequest())
    expect(requestBodyAt(fetchMock, 2)._app_secret_request).toEqual(noSecretRequest())
  })

  it("preserves missing Core Secrets grants as operational errors", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          action: "calendar_connections.start_oauth",
          error: "missing_secret_grant",
          detail: "Google OAuth client id is unavailable through Core Secrets.",
        },
        { status: 403 },
      ),
    )
    vi.stubGlobal("fetch", fetchMock)

    await expect(startGoogleOAuth("calendar", { redirectUri: "https://maverick.example/apps/calendar/oauth/callback" })).rejects.toMatchObject({
      code: "missing_secret_grant",
      detail: "Google OAuth client id is unavailable through Core Secrets.",
      status: 403,
    } satisfies Partial<CalendarApiError>)
  })
})

function jsonResponse(payload: Record<string, unknown>, init: ResponseInit = {}) {
  return new Response(JSON.stringify(payload), {
    status: init.status || 200,
    headers: { "content-type": "application/json" },
  })
}

function requestBody(fetchMock: ReturnType<typeof vi.fn>) {
  return requestBodyAt(fetchMock, 0)
}

function requestBodyAt(fetchMock: ReturnType<typeof vi.fn>, index: number) {
  const init = fetchMock.mock.calls[index]?.[1] as RequestInit | undefined
  return JSON.parse(String(init?.body || "{}")) as Record<string, unknown>
}

function googleEvent(id: string) {
  return {
    id,
    title: "Remote",
    startTime: new Date("2026-05-28T13:00:00Z"),
    endTime: new Date("2026-05-28T14:00:00Z"),
    color: "blue",
    revision: 1,
    source: "google_calendar",
    external_refs: {
      calendar_connection_id: "cal_conn_1",
      provider_calendar_id: "primary",
      provider_event_id: "google_evt_1",
    },
  }
}

function googleEventPayload(id: string) {
  return {
    ...googleEvent(id),
    startTime: "2026-05-28T13:00:00.000Z",
    endTime: "2026-05-28T14:00:00.000Z",
  }
}

function googleMutationSecretRequest(connectionId: string) {
  return {
    required: true,
    selectors: [
      {
        logical_names: ["google-oauth-client-id", "google-oauth-client-secret"],
      },
      {
        logical_names: ["google-calendar-refresh-token"],
        resource_type: "calendar_connection",
        resource_id: connectionId,
      },
    ],
  }
}

function noSecretRequest() {
  return {
    required: false,
    logical_names: [],
  }
}

function localEvent(id: string) {
  return {
    id,
    title: "Local",
    startTime: new Date("2026-05-28T13:00:00Z"),
    endTime: new Date("2026-05-28T14:00:00Z"),
    color: "blue",
    revision: 1,
  }
}

function localEventPayload(id: string) {
  return {
    ...localEvent(id),
    startTime: "2026-05-28T13:00:00.000Z",
    endTime: "2026-05-28T14:00:00.000Z",
  }
}
