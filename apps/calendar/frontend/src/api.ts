import type {
  CalendarActionResult,
  CalendarConnection,
  CalendarConnectionPayload,
  CalendarEvent,
  CalendarEventPayload,
  CalendarOAuthStartResult,
  CalendarRemoteCalendar,
  CalendarRemoteCalendarPayload,
  CalendarOAuthCompleteResult,
  CalendarSyncCalendarPayload,
  CalendarSyncResult,
  CalendarViewState,
} from './types';

export class CalendarApiError extends Error {
  code: string;
  detail: string;
  status: number;

  constructor(code: string, detail: string, status: number) {
    super(detail || code || 'Calendar request failed.');
    this.name = 'CalendarApiError';
    this.code = code;
    this.detail = detail;
    this.status = status;
  }
}

type AppSecretSelector = {
  logical_names: string[];
  resource_type?: string;
  resource_id?: string;
};

type AppSecretRequestPayload = {
  _app_secret_request: {
    required: boolean;
    selectors?: AppSecretSelector[];
    logical_names?: string[];
  };
};

const GOOGLE_OAUTH_CLIENT_ID_SECRET = 'google-oauth-client-id';
const GOOGLE_OAUTH_CLIENT_SECRET = 'google-oauth-client-secret';
const GOOGLE_CALENDAR_REFRESH_TOKEN_SECRET = 'google-calendar-refresh-token';
const CALENDAR_CONNECTION_RESOURCE_TYPE = 'calendar_connection';

const GOOGLE_OAUTH_CLIENT_ID_SELECTOR: AppSecretSelector = {
  logical_names: [GOOGLE_OAUTH_CLIENT_ID_SECRET],
};

const GOOGLE_OAUTH_CLIENT_CREDENTIALS_SELECTOR: AppSecretSelector = {
  logical_names: [GOOGLE_OAUTH_CLIENT_ID_SECRET, GOOGLE_OAUTH_CLIENT_SECRET],
};

function requiredAppSecrets(selectors: AppSecretSelector[]): AppSecretRequestPayload {
  return {
    _app_secret_request: {
      required: true,
      selectors,
    },
  };
}

function noAppSecrets(): AppSecretRequestPayload {
  return {
    _app_secret_request: {
      required: false,
      logical_names: [],
    },
  };
}

function googleCalendarRefreshTokenSelector(connectionId: string): AppSecretSelector {
  return {
    logical_names: [GOOGLE_CALENDAR_REFRESH_TOKEN_SECRET],
    resource_type: CALENDAR_CONNECTION_RESOURCE_TYPE,
    resource_id: connectionId,
  };
}

async function request(appId: string, body: Record<string, unknown>): Promise<CalendarActionResult> {
  const response = await fetch(`/api/apps/${encodeURIComponent(appId)}/backend`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const data = (await response.json()) as CalendarActionResult;
  if (!response.ok || data.error) {
    throw new CalendarApiError(data.error || 'calendar_request_failed', data.detail || data.error || 'Calendar request failed.', response.status);
  }
  return data;
}

export async function listEvents(appId: string): Promise<CalendarEvent[]> {
  const data = await request(appId, { action: 'list', ...noAppSecrets() });
  return (data.events || []).map(fromPayload);
}

export async function readViewFilter(appId: string): Promise<CalendarViewState> {
  const data = await request(appId, { action: 'view_filter', ...noAppSecrets() });
  return data.view_state || {};
}

export async function listConnections(appId: string): Promise<CalendarConnection[]> {
  const data = await request(appId, { action: 'calendar_connections.list', ...noAppSecrets() });
  return (data.connections || []).map(fromConnectionPayload);
}

export async function listCalendars(appId: string, connectionId?: string): Promise<CalendarRemoteCalendar[]> {
  const data = await request(appId, {
    action: 'calendar_calendars.list',
    ...(connectionId ? { connection_id: connectionId } : {}),
    ...noAppSecrets(),
  });
  return (data.calendars || []).map((calendar) => fromCalendarPayload(calendar as CalendarRemoteCalendarPayload));
}

export async function selectCalendar(
  appId: string,
  connectionId: string,
  calendarId: string,
  options: { selected?: boolean; syncEnabled?: boolean },
): Promise<CalendarRemoteCalendar> {
  const data = await request(appId, {
    action: 'calendar_calendars.select',
    connection_id: connectionId,
    calendar_id: calendarId,
    ...(options.selected !== undefined ? { selected: options.selected } : {}),
    ...(options.syncEnabled !== undefined ? { sync_enabled: options.syncEnabled } : {}),
    ...noAppSecrets(),
  });
  if (!data.calendar) {
    throw new CalendarApiError('invalid_calendar_selection', 'Calendar did not return the selected Google calendar.', 500);
  }
  return fromCalendarPayload(data.calendar);
}

export async function startGoogleOAuth(appId: string, options: { redirectUri: string }): Promise<CalendarOAuthStartResult> {
  const data = await request(appId, {
    action: 'calendar_connections.start_oauth',
    provider: 'google',
    redirect_uri: options.redirectUri,
    ...requiredAppSecrets([GOOGLE_OAUTH_CLIENT_ID_SELECTOR]),
  });
  if (!data.authorization_url || !data.state) {
    throw new CalendarApiError('invalid_oauth_start', 'Calendar did not return a Google authorization URL.', 500);
  }
  return {
    action: data.action,
    provider: data.provider || 'google',
    authorization_url: data.authorization_url,
    state: data.state,
    expires_at: data.expires_at,
    connection: data.connection ? fromConnectionPayload(data.connection) : undefined,
  };
}

export async function completeGoogleOAuth(
  appId: string,
  options: { code: string; state: string; redirectUri: string },
): Promise<CalendarOAuthCompleteResult> {
  const data = await request(appId, {
    action: 'calendar_connections.complete_oauth',
    provider: 'google',
    code: options.code,
    state: options.state,
    redirect_uri: options.redirectUri,
    ...requiredAppSecrets([GOOGLE_OAUTH_CLIENT_CREDENTIALS_SELECTOR]),
  });
  if (!data.connection) {
    throw new CalendarApiError('invalid_oauth_completion', 'Calendar did not return a connected Google Calendar account.', 500);
  }
  return {
    action: data.action,
    provider: data.provider || 'google',
    connection: fromConnectionPayload(data.connection),
  };
}

export async function syncCalendar(
  appId: string,
  connectionId: string,
  options: { calendarId?: string; fullSync?: boolean } = {},
): Promise<CalendarSyncResult> {
  const body: Record<string, unknown> = {
    action: 'calendar_sync',
    connection_id: connectionId,
    ...requiredAppSecrets([
      GOOGLE_OAUTH_CLIENT_CREDENTIALS_SELECTOR,
      googleCalendarRefreshTokenSelector(connectionId),
    ]),
  };
  if (options.calendarId) {
    body.calendar_id = options.calendarId;
  }
  if (options.fullSync !== undefined) {
    body.full_sync = options.fullSync;
  }
  const data = await request(appId, body);
  return {
    action: data.action,
    provider: data.provider,
    connection_id: data.connection_id,
    synced: Boolean(data.synced),
    calendar_count: data.calendar_count || 0,
    events_changed: data.events_changed || 0,
    created: data.created || 0,
    updated: data.updated || 0,
    deleted: data.deleted || 0,
    unchanged: data.unchanged || 0,
    full_resyncs: data.full_resyncs || 0,
    calendars: (data.calendars || []) as CalendarSyncCalendarPayload[],
  };
}

export async function createEvent(
  appId: string,
  event: Omit<CalendarEvent, 'id'> & { id?: string },
): Promise<CalendarEvent> {
  const eventPayload = toPayload(event, { includeId: false, includeIdempotencyKey: true });
  const data = await request(appId, {
    action: 'create',
    event: eventPayload,
    ...remoteMutationSecretRequest(eventPayload),
  });
  if (!data.event) {
    throw new Error('Calendar event was not created.');
  }
  return fromPayload(data.event);
}

export async function updateEvent(appId: string, id: string, event: Partial<CalendarEvent>): Promise<CalendarEvent> {
  const eventPayload = toPayload(event);
  const body: Record<string, unknown> = {
    action: 'update',
    id,
    event: eventPayload,
    ...remoteMutationSecretRequest(eventPayload),
  };
  if (event.revision !== undefined) {
    body.expected_revision = event.revision;
  }
  const data = await request(appId, body);
  if (!data.event) {
    throw new Error('Calendar event was not saved.');
  }
  return fromPayload(data.event);
}

export async function deleteEvent(appId: string, id: string, expectedRevision?: number, event?: Partial<CalendarEvent>): Promise<void> {
  const eventPayload = event ? toPayload(event) : {};
  const body: Record<string, unknown> = {
    action: 'delete',
    id,
    ...remoteMutationSecretRequest(eventPayload),
  };
  if (expectedRevision !== undefined) {
    body.expected_revision = expectedRevision;
  }
  await request(appId, body);
}

function remoteMutationSecretRequest(event: Partial<CalendarEventPayload>): AppSecretRequestPayload {
  const connectionId = googleCalendarConnectionId(event.external_refs);
  const provider = googleCalendarProvider(event.external_refs);
  if (!connectionId || (event.source !== 'google_calendar' && provider !== 'google')) {
    return noAppSecrets();
  }
  return requiredAppSecrets([
    GOOGLE_OAUTH_CLIENT_CREDENTIALS_SELECTOR,
    googleCalendarRefreshTokenSelector(connectionId),
  ]);
}

function googleCalendarConnectionId(refs: unknown): string {
  if (!refs || typeof refs !== 'object') {
    return '';
  }
  const record = refs as Record<string, unknown>;
  const value = record.calendar_connection_id || record.calendarConnectionId || record.connection_id || record.connectionId;
  return typeof value === 'string' ? value.trim() : '';
}

function googleCalendarProvider(refs: unknown): string {
  if (!refs || typeof refs !== 'object') {
    return '';
  }
  const value = (refs as Record<string, unknown>).provider;
  return typeof value === 'string' ? value.trim().toLowerCase() : '';
}

function fromConnectionPayload(connection: CalendarConnectionPayload): CalendarConnection {
  return {
    ...connection,
    provider: connection.provider || 'google',
    scopes: connection.scopes || [],
    external_refs: connection.external_refs || {},
  };
}

function fromCalendarPayload(calendar: CalendarRemoteCalendarPayload): CalendarRemoteCalendar {
  return {
    ...calendar,
    provider: calendar.provider || 'google',
    summary: calendar.summary || '',
    description: calendar.description || '',
    timezone: calendar.timezone || 'UTC',
    access_role: calendar.access_role || '',
    primary: Boolean(calendar.primary),
    selected: calendar.selected !== false,
    sync_enabled: calendar.sync_enabled !== false,
    color: calendar.color || '',
  };
}

function fromPayload(event: CalendarEventPayload): CalendarEvent {
  return {
    ...event,
    startTime: new Date(event.startTime),
    endTime: new Date(event.endTime),
    timezone: event.timezone || 'UTC',
    all_day: event.all_day || false,
    attendees: event.attendees || [],
    tags: event.tags || [],
    external_refs: event.external_refs || {},
    recurrence: event.recurrence || {},
    reminders: event.reminders || []
  };
}

function toPayload(
  event: Partial<CalendarEvent>,
  options: { includeId?: boolean; includeIdempotencyKey?: boolean } = {},
): Partial<CalendarEventPayload> {
  const payload: Partial<CalendarEventPayload> = {};
  if (options.includeId !== false && event.id !== undefined) payload.id = event.id;
  if (event.title !== undefined) payload.title = event.title;
  if (event.description !== undefined) payload.description = event.description;
  if (event.startTime !== undefined) payload.startTime = event.startTime.toISOString();
  if (event.endTime !== undefined) payload.endTime = event.endTime.toISOString();
  if (event.status !== undefined) payload.status = event.status;
  if (event.timezone !== undefined) payload.timezone = event.timezone;
  if (event.location !== undefined) payload.location = event.location;
  if (event.organizer !== undefined) payload.organizer = event.organizer;
  if (event.all_day !== undefined) payload.all_day = event.all_day;
  if (event.color !== undefined) payload.color = event.color;
  if (event.category !== undefined) payload.category = event.category;
  if (event.attendees !== undefined) payload.attendees = event.attendees;
  if (event.tags !== undefined) payload.tags = event.tags;
  if (event.source !== undefined) payload.source = event.source;
  if (event.external_refs !== undefined) payload.external_refs = event.external_refs;
  if (event.recurrence !== undefined) payload.recurrence = event.recurrence;
  if (event.reminders !== undefined) payload.reminders = event.reminders;
  if (options.includeIdempotencyKey && event.idempotency_key !== undefined) payload.idempotency_key = event.idempotency_key;
  return payload;
}
