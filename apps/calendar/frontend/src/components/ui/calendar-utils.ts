import type {
  CalendarAccount,
  CalendarColor,
  CalendarConnection,
  CalendarRemoteCalendar,
  CalendarExternalViewState,
  CalendarSourceOption,
  CalendarView,
  DraftEvent,
  Event,
} from "./calendar-types"

export const defaultColors: CalendarColor[] = [
  { name: "Blue", value: "blue", bg: "bg-blue-500", text: "text-blue-700" },
  { name: "Green", value: "green", bg: "bg-green-500", text: "text-green-700" },
  { name: "Purple", value: "purple", bg: "bg-purple-500", text: "text-purple-700" },
  { name: "Orange", value: "orange", bg: "bg-orange-500", text: "text-orange-700" },
  { name: "Pink", value: "pink", bg: "bg-pink-500", text: "text-pink-700" },
  { name: "Red", value: "red", bg: "bg-red-500", text: "text-red-700" },
]

export function isWritableGoogleAccessRole(accessRole: unknown) {
  const role = scalarString(accessRole).toLowerCase()
  return role === "owner" || role === "writer"
}

export function eventsForDate(events: Event[], date: Date) {
  const dayStart = new Date(date)
  dayStart.setHours(0, 0, 0, 0)
  const dayEnd = new Date(dayStart)
  dayEnd.setDate(dayEnd.getDate() + 1)
  return events
    .filter((event) => event.startTime < dayEnd && event.endTime > dayStart)
    .sort((a, b) => a.startTime.getTime() - b.startTime.getTime())
}

export function eventsForHour(events: Event[], date: Date, hour: number) {
  const hourStart = new Date(date)
  hourStart.setHours(hour, 0, 0, 0)
  const hourEnd = new Date(hourStart)
  hourEnd.setHours(hourEnd.getHours() + 1)
  return events
    .filter((event) => event.startTime < hourEnd && event.endTime > hourStart)
    .sort((a, b) => a.startTime.getTime() - b.startTime.getTime())
}

export function eventsForListDate(events: Event[], date: Date) {
  const dayStart = new Date(date)
  dayStart.setHours(0, 0, 0, 0)
  return events
    .filter((event) => event.endTime >= dayStart)
    .sort((a, b) => a.startTime.getTime() - b.startTime.getTime())
}

export function defaultDraft(date: Date, colors: { value: string }[], categories: string[]): DraftEvent {
  const startTime = new Date(date)
  const now = new Date()
  if (startTime.toDateString() === now.toDateString()) {
    startTime.setHours(now.getHours() + 1, 0, 0, 0)
  } else {
    startTime.setHours(9, 0, 0, 0)
  }
  const endTime = new Date(startTime)
  endTime.setHours(startTime.getHours() + 1)
  return {
    title: "",
    description: "",
    startTime,
    endTime,
    color: colors[0]?.value || "blue",
    category: categories[0] || "Meeting",
    attendees: [],
    tags: [],
    source: "calendar",
    external_refs: {},
  }
}

export function calendarAccountValue(event: Event) {
  return calendarAccountFromExternalRefs(event.external_refs).value || scalarString(event.source) || "calendar"
}

export function calendarAccountFilterValues(event: Event) {
  const refs = calendarAccountFromExternalRefs(event.external_refs)
  return uniqueStrings([refs.connectionId, refs.value, scalarString(event.source) || "calendar"])
}

export function calendarAccountOptions(events: Event[], connections: CalendarConnection[] = []): CalendarAccount[] {
  const byValue = new Map<string, CalendarAccount>()
  connections.forEach((connection) => {
    const accountId = scalarString(connection.account_id)
    const connectionId = scalarString(connection.id)
    const value = connectionId || accountId
    if (!value || byValue.has(value)) {
      return
    }
    byValue.set(value, compactAccountOption({
      value,
      name: scalarString(connection.account_label) || accountId || accountLabel(value),
      accountId,
      connectionId,
      provider: scalarString(connection.provider),
      status: scalarString(connection.status),
    }))
  })
  events.forEach((event) => {
    const externalAccount = calendarAccountFromExternalRefs(event.external_refs)
    const value = externalAccount.connectionId && byValue.has(externalAccount.connectionId)
      ? externalAccount.connectionId
      : calendarAccountValue(event)
    if (!byValue.has(value)) {
      byValue.set(value, compactAccountOption({
        value,
        name: externalAccount.label || accountLabel(value),
        accountId: externalAccount.value,
        connectionId: externalAccount.connectionId,
        provider: externalAccount.provider,
      }))
    }
  })
  return [...byValue.values()].sort((a, b) => a.name.localeCompare(b.name))
}

export function calendarSourceOptions(
  events: Event[],
  connections: CalendarConnection[] = [],
  calendars: CalendarRemoteCalendar[] = [],
): CalendarSourceOption[] {
  const byValue = new Map<string, CalendarSourceOption>()
  byValue.set("local", {
    value: "local",
    name: "Local calendar",
    source: "calendar",
    accountName: "Local",
    accountValue: "calendar",
    calendarName: "Local calendar",
    externalRefs: {},
  })
  connections.forEach((connection) => {
    const connectionId = scalarString(connection.id)
    if (!connectionId) {
      return
    }
    const connectionCalendars = calendars.filter((calendar) => scalarString(calendar.connection_id) === connectionId)
    if (connectionCalendars.length > 0) {
      return
    }
    const primaryCalendar = connectionCalendars.find((calendar) => scalarString(calendar.provider_calendar_id) === "primary")
    const defaultCalendar = primaryCalendar || connectionCalendars.find((calendar) => calendar.selected !== false) || connectionCalendars[0]
    const providerCalendarId = scalarString(defaultCalendar?.provider_calendar_id) || "primary"
    const providerCalendarSummary = scalarString(defaultCalendar?.summary) || (providerCalendarId === "primary" ? "Primary calendar" : providerCalendarId)
    const provider = scalarString(defaultCalendar?.provider) || scalarString(connection.provider) || "google"
    const accessRole = scalarString(defaultCalendar?.access_role)
    const writable = !accessRole || isWritableGoogleAccessRole(accessRole)
    const accountId = scalarString(connection.account_id)
    const accountName = scalarString(connection.account_label) || accountId || accountLabel(connectionId)
    byValue.set(`connection:${connectionId}`, {
      value: `connection:${connectionId}`,
      name: accountName,
      source: providerSource(provider),
      provider,
      accountName,
      accountValue: connectionId,
      connectionId,
      providerCalendarId,
      calendarName: providerCalendarSummary,
      accessRole,
      writable,
      externalRefs: {
        calendar_account_id: accountId,
        calendar_account_label: accountName,
        calendar_connection_id: connectionId,
        provider,
        provider_calendar_id: providerCalendarId,
        provider_calendar_summary: providerCalendarSummary,
        provider_calendar_access_role: accessRole,
      },
    })
  })
  calendars.forEach((calendar) => {
    const connectionId = scalarString(calendar.connection_id)
    const providerCalendarId = scalarString(calendar.provider_calendar_id)
    if (!connectionId || !providerCalendarId) {
      return
    }
    const connection = connections.find((item) => scalarString(item.id) === connectionId)
    const accountId = scalarString(connection?.account_id)
    const accountName = scalarString(connection?.account_label) || accountId || accountLabel(connectionId)
    const calendarName = scalarString(calendar.summary) || providerCalendarId
    const accessRole = scalarString(calendar.access_role)
    byValue.set(`calendar:${connectionId}:${providerCalendarId}`, {
      value: `calendar:${connectionId}:${providerCalendarId}`,
      name: [accountName, calendarName].filter(Boolean).join(" / ") || calendarName,
      source: "google_calendar",
      provider: scalarString(calendar.provider) || scalarString(connection?.provider) || "google",
      accountName,
      accountValue: connectionId,
      connectionId,
      providerCalendarId,
      calendarName,
      accessRole,
      writable: !accessRole || isWritableGoogleAccessRole(accessRole),
      externalRefs: {
        provider: scalarString(calendar.provider) || scalarString(connection?.provider) || "google",
        calendar_account_id: accountId,
        calendar_account_label: accountName,
        calendar_connection_id: connectionId,
        provider_calendar_id: providerCalendarId,
        provider_calendar_summary: calendarName,
        provider_calendar_access_role: accessRole,
      },
    })
  })
  events.forEach((event) => {
    const details = eventSourceDetails(event, connections)
    if (!details.connectionId && !details.providerCalendarId) {
      return
    }
    const value = `calendar:${details.connectionId || details.accountValue || "event"}:${details.providerCalendarId || "default"}`
    if (byValue.has(value) || matchesExistingConnectionFallback(byValue, details.connectionId, details.providerCalendarId)) {
      return
    }
    byValue.set(value, {
      value,
      name: [details.accountName, details.calendarName].filter(Boolean).join(" / ") || details.calendarName || details.accountName || "Google Calendar",
      source: "google_calendar",
      provider: details.provider || "google",
      accountName: details.accountName,
      accountValue: details.connectionId || details.accountValue,
      connectionId: details.connectionId,
      providerCalendarId: details.providerCalendarId,
      calendarName: details.calendarName,
      accessRole: details.accessRole,
      writable: !details.accessRole || isWritableGoogleAccessRole(details.accessRole),
      externalRefs: {
        provider: details.provider || "google",
        calendar_account_id: details.accountId,
        calendar_account_label: details.accountName,
        calendar_connection_id: details.connectionId,
        provider_calendar_id: details.providerCalendarId,
        provider_calendar_summary: details.calendarName,
        provider_calendar_access_role: details.accessRole,
      },
    })
  })
  return [...byValue.values()]
}

export function selectedCalendarSourceValue(event: DraftEvent | Event | null | undefined, options: CalendarSourceOption[]) {
  if (!event) {
    return "local"
  }
  const details = eventSourceDetails(event, [])
  if (details.connectionId && details.providerCalendarId) {
    const calendarValue = `calendar:${details.connectionId}:${details.providerCalendarId}`
    if (options.some((option) => option.value === calendarValue)) {
      return calendarValue
    }
  }
  if (details.connectionId) {
    const connectionValue = `connection:${details.connectionId}`
    if (options.some((option) => option.value === connectionValue)) {
      return connectionValue
    }
  }
  return scalarString(event.source) === "google_calendar" ? options.find((option) => option.source === "google_calendar")?.value || "local" : "local"
}

export function calendarSourcePatch(event: DraftEvent | Event | null | undefined, value: string, options: CalendarSourceOption[]): DraftEvent {
  const selected = options.find((option) => option.value === value) || options[0]
  const retainedRefs = stripCalendarRefs(event?.external_refs)
  return {
    source: selected?.source || "calendar",
    external_refs: {
      ...retainedRefs,
      ...(selected?.externalRefs || {}),
    },
  }
}

export function eventSourceDetails(event: Pick<Event, "source" | "external_refs"> | Pick<DraftEvent, "source" | "external_refs">, connections: CalendarConnection[] = []) {
  const refs = calendarAccountFromExternalRefs(event.external_refs)
  const connection = connections.find((item) => {
    const itemConnectionId = scalarString(item.id)
    const itemAccountId = scalarString(item.account_id)
    return (refs.connectionId && itemConnectionId === refs.connectionId) || (refs.value && itemAccountId === refs.value)
  })
  const accountId = refs.value || scalarString(connection?.account_id)
  const connectionId = refs.connectionId || scalarString(connection?.id)
  const accountName = refs.label || scalarString(connection?.account_label) || accountId || accountLabel(connectionId)
  const provider = refs.provider || scalarString(connection?.provider) || (scalarString(event.source) === "google_calendar" ? "google" : "")
  const source = scalarString(event.source) || (provider === "google" ? "google_calendar" : "calendar")
  return {
    source,
    sourceLabel: sourceLabel(source, provider),
    provider,
    accountId,
    accountValue: connectionId || accountId || source,
    accountName,
    connectionId,
    providerCalendarId: refs.providerCalendarId,
    calendarName: refs.providerCalendarSummary || refs.providerCalendarId || (provider === "google" ? "Google Calendar" : "Local calendar"),
    accessRole: refs.providerCalendarAccessRole,
    remoteLink: refs.remoteLink,
  }
}

export function eventIsReadOnly(event: Pick<Event, "source" | "external_refs"> | Pick<DraftEvent, "source" | "external_refs">, calendars: CalendarRemoteCalendar[] = []) {
  const details = eventSourceDetails(event, [])
  if (details.source !== "google_calendar" && details.provider !== "google") {
    return false
  }
  const calendar = calendars.find((item) =>
    scalarString(item.connection_id) === details.connectionId &&
    scalarString(item.provider_calendar_id) === details.providerCalendarId
  )
  const accessRole = scalarString(calendar?.access_role) || details.accessRole
  return Boolean(accessRole && !isWritableGoogleAccessRole(accessRole))
}

function matchesExistingConnectionFallback(
  options: Map<string, CalendarSourceOption>,
  connectionId: string,
  providerCalendarId: string,
) {
  if (!connectionId || !providerCalendarId) {
    return false
  }
  const option = options.get(`connection:${connectionId}`)
  return option?.providerCalendarId === providerCalendarId
}

export function viewportFromViewState(
  viewState: CalendarExternalViewState | undefined,
  events: Event[],
  defaultView: CalendarView,
) {
  const mode = scalarString(viewState?.mode)
  if (!mode || mode === "default") {
    return { date: new Date(), view: defaultView }
  }
  if (mode === "custom") {
    const ids = Array.isArray(viewState?.entity_ids) ? viewState.entity_ids : []
    const firstVisibleEvent = ids.map((id) => events.find((event) => event.id === id)).find(Boolean)
    if (firstVisibleEvent) {
      return {
        date: firstVisibleEvent.startTime,
        view: (ids.length === 1 ? "day" : "list") as CalendarView,
      }
    }
    return { date: new Date(), view: "list" as CalendarView, pendingEventResolution: ids.length > 0 && events.length === 0 }
  }
  const start = dateFromString(viewState?.start_after)
  const end = dateFromString(viewState?.end_before)
  const date = start || events[0]?.startTime || new Date()
  return { date, view: viewForWindow(start, end) }
}

export function viewStateSignature(viewState: CalendarExternalViewState | undefined) {
  return JSON.stringify({
    mode: scalarString(viewState?.mode) || "default",
    query: scalarString(viewState?.query),
    start_after: scalarString(viewState?.start_after),
    end_before: scalarString(viewState?.end_before),
    category: scalarString(viewState?.category),
    attendee: scalarString(viewState?.attendee),
    tags: arrayOfStrings(viewState?.tags),
    conflicts_only: Boolean(viewState?.conflicts_only),
    entity_ids: arrayOfStrings(viewState?.entity_ids),
  })
}

function viewForWindow(start: Date | null, end: Date | null): CalendarView {
  if (!start || !end) {
    return "list"
  }
  const durationDays = Math.max(0, (end.getTime() - start.getTime()) / 86400000)
  if (durationDays <= 1) {
    return "day"
  }
  if (durationDays <= 8) {
    return "week"
  }
  return "month"
}

function dateFromString(value: unknown) {
  const text = scalarString(value)
  if (!text) return null
  const date = new Date(text)
  return Number.isNaN(date.getTime()) ? null : date
}

function arrayOfStrings(value: unknown) {
  return Array.isArray(value) ? value.map((item) => scalarString(item)).filter(Boolean) : []
}

function scalarString(value: unknown) {
  return typeof value === "string" ? value.trim() : ""
}

function accountLabel(value: string) {
  if (value.includes("@") || value.includes(".")) {
    return value
  }
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (letter) => letter.toLocaleUpperCase())
}

function calendarAccountFromExternalRefs(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return { value: "", label: "", connectionId: "", providerCalendarId: "", providerCalendarSummary: "", providerCalendarAccessRole: "", provider: "", remoteLink: "" }
  }
  const refs = value as Record<string, unknown>
  return {
    value: firstString(refs, ["calendar_account", "calendar_account_id", "calendarAccount", "calendarAccountId", "account", "account_id"]),
    label: firstString(refs, ["calendar_account_label", "calendarAccountLabel", "account_label", "accountLabel"]),
    connectionId: firstString(refs, ["calendar_connection_id", "calendarConnectionId", "connection_id", "connectionId"]),
    providerCalendarId: firstString(refs, ["provider_calendar_id", "providerCalendarId", "google_calendar_id", "googleCalendarId"]),
    providerCalendarSummary: firstString(refs, ["provider_calendar_summary", "providerCalendarSummary", "calendar_name", "calendarName"]),
    providerCalendarAccessRole: firstString(refs, ["provider_calendar_access_role", "providerCalendarAccessRole", "access_role", "accessRole"]),
    provider: firstString(refs, ["provider"]),
    remoteLink: firstString(refs, ["html_link", "htmlLink", "remote_link", "remoteLink"]),
  }
}

function firstString(record: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = scalarString(record[key])
    if (value) {
      return value
    }
  }
  return ""
}

function uniqueStrings(values: string[]) {
  return [...new Set(values.filter(Boolean))]
}

function compactAccountOption(option: CalendarAccount): CalendarAccount {
  return Object.fromEntries(Object.entries(option).filter(([, value]) => value !== "" && value !== undefined)) as CalendarAccount
}

function providerSource(provider: unknown) {
  return scalarString(provider) === "google" ? "google_calendar" : scalarString(provider) || "calendar"
}

function sourceLabel(source: string, provider: string) {
  if (source === "google_calendar" || provider === "google") {
    return "Google"
  }
  return "Local"
}

function stripCalendarRefs(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {}
  }
  const refs = { ...(value as Record<string, unknown>) }
  const keys = [
    "provider",
    "calendar_account",
    "calendar_account_id",
    "calendarAccount",
    "calendarAccountId",
    "account",
    "account_id",
    "calendar_account_label",
    "calendarAccountLabel",
    "account_label",
    "accountLabel",
    "calendar_connection_id",
    "calendarConnectionId",
    "connection_id",
    "connectionId",
    "provider_calendar_id",
    "providerCalendarId",
    "google_calendar_id",
    "googleCalendarId",
    "provider_calendar_summary",
    "providerCalendarSummary",
    "calendar_name",
    "calendarName",
    "provider_calendar_access_role",
    "providerCalendarAccessRole",
    "access_role",
    "accessRole",
    "provider_event_id",
    "providerEventId",
    "google_event_id",
    "googleEventId",
    "html_link",
    "htmlLink",
    "remote_link",
    "remoteLink",
    "etag",
    "eTag",
    "ical_uid",
    "icalUid",
    "iCalUID",
    "iCalUid",
    "icalUID",
  ]
  keys.forEach((key) => delete refs[key])
  return refs
}

export function validateDraft(event: DraftEvent | Event) {
  if (!event.title?.trim()) return "Title is required."
  if (!event.startTime || Number.isNaN(event.startTime.getTime())) return "Start time is required."
  if (!event.endTime || Number.isNaN(event.endTime.getTime())) return "End time is required."
  if (event.endTime <= event.startTime) return "End time must be after start time."
  return ""
}

export function formatTime(date: Date) {
  return date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })
}

export function inputDate(date?: Date) {
  return date ? new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16) : ""
}
