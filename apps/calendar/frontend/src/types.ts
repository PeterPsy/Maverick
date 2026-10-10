import type { CalendarConnection, CalendarRemoteCalendar, Event } from './components/ui/calendar-types';

export type CalendarEvent = Event;
export type { CalendarConnection, CalendarRemoteCalendar };

export interface CalendarActionResult {
  local_event_count?: number;
  conflicts?: Array<{ id: string; title: string; startTime: string; endTime: string }>;
  pagination?: { has_more?: boolean; total?: number };
  actual_revision?: number;
  current_event?: CalendarEventPayload;
  slots?: Array<{ startTime: string; endTime: string }>;
  action?: string;
  event?: CalendarEventPayload;
  events?: CalendarEventPayload[];
  connection?: CalendarConnectionPayload;
  connections?: CalendarConnectionPayload[];
  calendar?: CalendarRemoteCalendarPayload;
  calendars?: Array<CalendarRemoteCalendarPayload | CalendarSyncCalendarPayload>;
  provider?: string;
  authorization_url?: string;
  state?: string;
  expires_at?: string;
  connection_id?: string;
  synced?: boolean;
  calendar_count?: number;
  events_changed?: number;
  created?: number;
  updated?: number;
  deleted?: number;
  unchanged?: number;
  full_resyncs?: number;
  view_state?: CalendarViewState;
  error?: string;
  detail?: string;
}

export interface CalendarRemoteCalendarPayload {
  id: string;
  connection_id: string;
  provider: string;
  provider_calendar_id: string;
  summary?: string;
  description?: string;
  timezone?: string;
  access_role?: string;
  primary?: boolean;
  selected?: boolean;
  availability_enabled?: boolean
  sync_status?: { status?: string; last_sync_at?: string; time_min?: string; time_max?: string; error?: string; has_more?: boolean }
  sync_enabled?: boolean;
  color?: string;
  updated_at?: string;
}

export interface CalendarEventPayload {
  id: string;
  title: string;
  description?: string;
  startTime: string;
  endTime: string;
  status?: 'confirmed' | 'tentative' | 'cancelled';
  series_id?: string
  original_start_time?: string
  recurrence_scope?: "occurrence" | "future" | "series"
  transparency?: "opaque" | "transparent"
  all_day_start?: string
  all_day_end?: string
  timezone?: string;
  location?: string;
  organizer?: string;
  all_day?: boolean;
  color: string;
  category?: string;
  attendees?: string[];
  attendee_details?: CalendarEvent['attendee_details'];
  conference?: CalendarEvent['conference'];
  tags?: string[];
  created_at?: string;
  updated_at?: string;
  revision?: number;
  source?: string;
  external_refs?: Record<string, unknown>;
  recurrence?: Record<string, unknown>;
  reminders_use_default?: boolean
  reminders?: unknown[];
  idempotency_key?: string;
}

export interface CalendarConnectionPayload {
  id: string;
  resource_type?: string;
  provider: string;
  account_id?: string;
  account_label?: string;
  status?: string;
  scopes?: string[];
  created_at?: string;
  updated_at?: string;
  event_count?: number;
  sync_status?: { status?: string; last_sync_at?: string; stale?: boolean; error?: string };
  last_sync_at?: string;
  token_resource?: {
    logical_name?: string;
    resource_type?: string;
    resource_id?: string;
  };
  external_refs?: Record<string, unknown>;
}

export interface CalendarSyncCalendarPayload {
  calendar_id?: string;
  provider_calendar_id?: string;
  full_sync?: boolean;
  pages?: number;
  truncated?: boolean;
  created?: number;
  updated?: number;
  deleted?: number;
  unchanged?: number;
  sync_token_updated?: boolean;
}

export interface CalendarSyncResult {
  action?: string;
  provider?: string;
  connection_id?: string;
  synced: boolean;
  calendar_count: number;
  events_changed: number;
  created: number;
  updated: number;
  deleted: number;
  unchanged: number;
  full_resyncs: number;
  calendars: CalendarSyncCalendarPayload[];
}

export interface CalendarOAuthStartResult {
  action?: string;
  provider?: string;
  authorization_url: string;
  state: string;
  expires_at?: string;
  connection?: CalendarConnection;
}

export interface CalendarOAuthCompleteResult {
  action?: string;
  provider?: string;
  connection: CalendarConnection;
}

export interface CalendarViewState {
  schema_version?: string;
  mode?: string;
  title?: string;
  query?: string;
  start_after?: string;
  end_before?: string;
  category?: string;
  attendee?: string;
  tags?: string[];
  conflicts_only?: boolean;
  entity_ids?: string[];
  references?: CalendarReference[];
}

export interface CalendarReference {
  app_id?: string;
  entity_type?: string;
  entity_id?: string;
  app_page?: string;
  deep_link?: string;
}
