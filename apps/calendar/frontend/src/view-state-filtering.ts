import type { Event } from "./components/ui/event-manager"
import type { CalendarViewState } from "./types"

export function sortEvents(events: Event[]) {
  return [...events].sort((a, b) => a.startTime.getTime() - b.startTime.getTime());
}

export function applyViewState(events: Event[], viewState: CalendarViewState, focusEventId = '') {
  const mode = scalarString(viewState.mode) || 'default';
  const entityIds = arrayOfStrings(viewState.entity_ids);
  let visible = events;

  if (mode === 'custom' && entityIds.length > 0) {
    const byId = new Map(events.map((event) => [event.id, event]));
    visible = entityIds.map((id) => byId.get(id)).filter((event): event is Event => Boolean(event));
  }
  if (mode !== 'default') {
    visible = visible.filter((event) => matchesViewState(event, viewState));
  }
  if (viewState.conflicts_only) {
    visible = visible.filter((event) => eventHasConflict(event, events));
  }

  if (focusEventId && !visible.some((event) => event.id === focusEventId)) {
    const focused = events.find((event) => event.id === focusEventId);
    if (focused) {
      visible = [focused, ...visible];
    }
  }

  return sortEvents(visible);
}

function matchesViewState(event: Event, viewState: CalendarViewState) {
  const query = foldString(viewState.query);
  const category = foldString(viewState.category);
  const attendee = foldString(viewState.attendee);
  const tags = new Set(arrayOfStrings(viewState.tags).map((tag) => foldString(tag)));
  const startAfter = dateFromString(viewState.start_after);
  const endBefore = dateFromString(viewState.end_before);

  if (startAfter && event.endTime <= startAfter) return false;
  if (endBefore && event.startTime >= endBefore) return false;
  if (category && foldString(event.category) !== category) return false;
  if (attendee && !(event.attendees || []).some((item) => foldString(item) === attendee)) return false;
  if (tags.size > 0 && !(event.tags || []).some((tag) => tags.has(foldString(tag)))) return false;
  if (query && !eventSearchText(event).includes(query)) return false;
  return true;
}

function eventHasConflict(event: Event, events: Event[]) {
  if (!eventBlocksAvailability(event)) {
    return false;
  }
  return events.some((candidate) => {
    if (candidate.id === event.id || !eventBlocksAvailability(candidate)) {
      return false;
    }
    if (candidate.endTime <= event.startTime || candidate.startTime >= event.endTime) {
      return false;
    }
    const eventAttendees = new Set((event.attendees || []).map((item) => foldString(item)));
    const candidateAttendees = new Set((candidate.attendees || []).map((item) => foldString(item)));
    if (eventAttendees.size > 0 && candidateAttendees.size > 0) {
      return [...eventAttendees].some((attendee) => candidateAttendees.has(attendee));
    }
    return true;
  });
}

function eventBlocksAvailability(event: Event) {
  return (event.status || 'confirmed') !== 'cancelled';
}

function eventSearchText(event: Event) {
  return [
    event.title,
    event.description || '',
    event.category || '',
    event.location || '',
    event.organizer || '',
    ...(event.attendees || []),
    ...(event.tags || [])
  ]
    .join(' ')
    .normalize('NFKC')
    .toLocaleLowerCase();
}

function arrayOfStrings(value: unknown) {
  return Array.isArray(value) ? value.map((item) => scalarString(item)).filter(Boolean) : [];
}

function dateFromString(value: unknown) {
  const text = scalarString(value);
  if (!text) return null;
  const date = new Date(text);
  return Number.isNaN(date.getTime()) ? null : date;
}

function scalarString(value: unknown) {
  return typeof value === 'string' ? value.trim() : '';
}

function foldString(value: unknown) {
  return scalarString(value).normalize('NFKC').toLocaleLowerCase();
}
