import { describe, expect, it } from "vitest"

import {
  calendarOAuthCallbackFromLocation,
  calendarOAuthRedirectUri,
  eventIdFromParams,
  mergeReloadMode,
  runtimeAppIdFromPathname,
} from "./runtime"

describe("runtime helpers", () => {
  it("derives the mounted app id from the direct app route", () => {
    expect(runtimeAppIdFromPathname("/apps/calendar/")).toBe("calendar")
    expect(runtimeAppIdFromPathname("/apps/team%20calendar/events")).toBe("team calendar")
    expect(runtimeAppIdFromPathname("/app/calendar/events")).toBe("calendar")
  })

  it("keeps full reloads sticky when merging reload modes", () => {
    expect(mergeReloadMode("view", "view")).toBe("view")
    expect(mergeReloadMode("view", "full")).toBe("full")
    expect(mergeReloadMode("full", "view")).toBe("full")
  })

  it("resolves event ids from direct params or app page paths", () => {
    expect(eventIdFromParams({ event_id: " evt_1 " })).toBe("evt_1")
    expect(eventIdFromParams({ app_page: "/events/evt_2" })).toBe("evt_2")
    expect(eventIdFromParams({ app_page: "events/evt%203" })).toBe("evt 3")
    expect(eventIdFromParams({ app_page: "settings" })).toBe("")
  })

  it("builds the Google Calendar OAuth callback URL for the mounted app", () => {
    expect(calendarOAuthRedirectUri("calendar", "https://maverick.example/")).toBe("https://maverick.example/apps/calendar/oauth/callback")
    expect(calendarOAuthRedirectUri("team calendar", "https://maverick.example")).toBe(
      "https://maverick.example/apps/team%20calendar/oauth/callback",
    )
  })

  it("recognizes Google Calendar OAuth callback routes", () => {
    expect(
      calendarOAuthCallbackFromLocation(
        "/apps/team%20calendar/oauth/callback",
        "?code= oauth-code &state= oauth-state ",
        "https://maverick.example",
      ),
    ).toEqual({
      appId: "team calendar",
      code: "oauth-code",
      state: "oauth-state",
      error: "",
      redirectUri: "https://maverick.example/apps/team%20calendar/oauth/callback",
    })
    expect(calendarOAuthCallbackFromLocation("/apps/calendar/events", "?code=ignored", "https://maverick.example")).toBeNull()
  })
})
