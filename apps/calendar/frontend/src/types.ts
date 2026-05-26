import type { Event } from './components/ui/event-manager';

export type CalendarEvent = Event;

export interface CalendarActionResult {
  action?: string;
  event?: CalendarEventPayload;
  events?: CalendarEventPayload[];
  view_state?: CalendarViewState;
  error?: string;
  detail?: string;
}

export interface CalendarEventPayload {
  id: string;
  title: string;
  description?: string;
  startTime: string;
  endTime: string;
  status?: 'confirmed' | 'tentative' | 'cancelled';
  timezone?: string;
  location?: string;
  organizer?: string;
  all_day?: boolean;
  color: string;
  category?: string;
  attendees?: string[];
  tags?: string[];
  created_at?: string;
  updated_at?: string;
  revision?: number;
  source?: string;
  external_refs?: Record<string, unknown>;
  recurrence?: Record<string, unknown>;
  reminders?: unknown[];
  idempotency_key?: string;
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
