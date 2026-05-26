export type CalendarSidebarMode = 'idle' | 'create' | 'details';

export type CalendarUiState = {
  searchQuery: string;
  selectedColors: string[];
  selectedTags: string[];
  selectedCategories: string[];
  selectedAccounts: string[];
  sidebarMode: CalendarSidebarMode;
  selectedEventId: string;
  requestId: string;
};

export const CALENDAR_UI_STATE_RESOURCE = 'ui-state';

const STORAGE_PREFIX = 'maverick.calendar.uiState';

const DEFAULT_UI_STATE: CalendarUiState = {
  searchQuery: '',
  selectedColors: [],
  selectedTags: [],
  selectedCategories: [],
  selectedAccounts: [],
  sidebarMode: 'idle',
  selectedEventId: '',
  requestId: '',
};

export function readCalendarUiState(appId: string): CalendarUiState {
  try {
    const raw = window.localStorage.getItem(storageKey(appId));
    if (!raw) {
      return { ...DEFAULT_UI_STATE };
    }
    const parsed = JSON.parse(raw) as Partial<CalendarUiState>;
    return normalizeUiState(parsed);
  } catch {
    return { ...DEFAULT_UI_STATE };
  }
}

export function writeCalendarUiState(appId: string, patch: Partial<CalendarUiState>): CalendarUiState {
  const next = normalizeUiState({ ...readCalendarUiState(appId), ...patch, requestId: patch.requestId || createRequestId() });
  window.localStorage.setItem(storageKey(appId), JSON.stringify(next));
  return next;
}

export function notifyCalendarUiStateChanged(appId: string, detail: Record<string, unknown> = {}) {
  window.parent?.postMessage(
    {
      type: 'maverick.app.data-changed',
      owner_app_id: appId,
      resource: CALENDAR_UI_STATE_RESOURCE,
      detail,
    },
    window.location.origin,
  );
}

function normalizeUiState(value: Partial<CalendarUiState>): CalendarUiState {
  return {
    searchQuery: scalarString(value.searchQuery),
    selectedColors: stringList(value.selectedColors),
    selectedTags: stringList(value.selectedTags),
    selectedCategories: stringList(value.selectedCategories),
    selectedAccounts: stringList(value.selectedAccounts),
    sidebarMode: value.sidebarMode === 'create' || value.sidebarMode === 'details' ? value.sidebarMode : 'idle',
    selectedEventId: scalarString(value.selectedEventId),
    requestId: scalarString(value.requestId),
  };
}

function storageKey(appId: string) {
  return `${STORAGE_PREFIX}.${appId || 'calendar'}`;
}

function scalarString(value: unknown) {
  return typeof value === 'string' ? value.trim() : '';
}

function stringList(value: unknown) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0).map((item) => item.trim());
}

function createRequestId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
