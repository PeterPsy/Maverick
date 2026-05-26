export interface Event {
  id: string
  title: string
  description?: string
  startTime: Date
  endTime: Date
  status?: "confirmed" | "tentative" | "cancelled"
  timezone?: string
  location?: string
  organizer?: string
  all_day?: boolean
  color: string
  category?: string
  attendees?: string[]
  tags?: string[]
  created_at?: string
  updated_at?: string
  revision?: number
  source?: string
  external_refs?: Record<string, unknown>
  recurrence?: Record<string, unknown>
  reminders?: unknown[]
  idempotency_key?: string
}

export interface EventManagerProps {
  events?: Event[]
  onEventCreate?: (event: Omit<Event, "id">) => void | Promise<void>
  onEventUpdate?: (id: string, event: Partial<Event>) => void | Promise<void>
  onEventDelete?: (id: string, event?: Event) => void | Promise<void>
  categories?: string[]
  colors?: CalendarColor[]
  defaultView?: CalendarView
  className?: string
  availableTags?: string[]
  focusEventId?: string
  focusVersion?: number
  viewState?: CalendarExternalViewState
  onEventOpen?: (event: Event) => void
  runtimeAppId?: string
}

export interface CalendarColor {
  name: string
  value: string
  bg: string
  text: string
}

export interface CalendarAccount {
  name: string
  value: string
}

export interface ColorClasses {
  name?: string
  bg: string
  text: string
}

export type CalendarView = "month" | "week" | "day" | "list"
export type DraftEvent = Partial<Event>

export interface CalendarExternalViewState {
  mode?: string
  query?: string
  start_after?: string
  end_before?: string
  category?: string
  attendee?: string
  tags?: string[]
  conflicts_only?: boolean
  entity_ids?: string[]
}

export interface ViewProps {
  currentDate: Date
  events: Event[]
  onEventClick: (event: Event) => void
  onDragStart: (event: Event) => void
  onDragEnd: () => void
  getColorClasses: (color: string) => ColorClasses
}
