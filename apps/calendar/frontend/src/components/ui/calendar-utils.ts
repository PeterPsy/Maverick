import type { CalendarAccount, CalendarColor, CalendarExternalViewState, CalendarView, DraftEvent, Event } from "./calendar-types"

export const defaultColors: CalendarColor[] = [
  { name: "Blue", value: "blue", bg: "bg-blue-500", text: "text-blue-700" },
  { name: "Green", value: "green", bg: "bg-green-500", text: "text-green-700" },
  { name: "Purple", value: "purple", bg: "bg-purple-500", text: "text-purple-700" },
  { name: "Orange", value: "orange", bg: "bg-orange-500", text: "text-orange-700" },
  { name: "Pink", value: "pink", bg: "bg-pink-500", text: "text-pink-700" },
  { name: "Red", value: "red", bg: "bg-red-500", text: "text-red-700" },
]

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
  }
}

export function calendarAccountValue(event: Event) {
  return calendarAccountFromExternalRefs(event.external_refs).value || scalarString(event.source) || "calendar"
}

export function calendarAccountOptions(events: Event[]): CalendarAccount[] {
  const byValue = new Map<string, CalendarAccount>()
  events.forEach((event) => {
    const value = calendarAccountValue(event)
    if (!byValue.has(value)) {
      const externalAccount = calendarAccountFromExternalRefs(event.external_refs)
      byValue.set(value, { value, name: externalAccount.label || accountLabel(value) })
    }
  })
  return [...byValue.values()].sort((a, b) => a.name.localeCompare(b.name))
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
    return { value: "", label: "" }
  }
  const refs = value as Record<string, unknown>
  return {
    value: firstString(refs, ["calendar_account", "calendar_account_id", "calendarAccount", "calendarAccountId", "account", "account_id"]),
    label: firstString(refs, ["calendar_account_label", "calendarAccountLabel", "account_label", "accountLabel"]),
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
