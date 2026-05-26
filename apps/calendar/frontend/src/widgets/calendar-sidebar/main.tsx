import { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { createEvent, deleteEvent, listEvents, updateEvent } from '../../api';
import {
  CALENDAR_UI_STATE_RESOURCE,
  notifyCalendarUiStateChanged,
  readCalendarUiState,
  writeCalendarUiState,
  type CalendarUiState,
} from '../../calendar-ui-state';
import { EventPanel } from '../../components/ui/calendar-event-panel';
import type { DraftEvent, Event } from '../../components/ui/calendar-types';
import { defaultColors, defaultDraft, validateDraft } from '../../components/ui/calendar-utils';
import { runtimeAppIdFromPathname } from '../../runtime';
import '../../styles/main.css';
import './styles.css';

const CATEGORIES = ['Meeting', 'Task', 'Reminder', 'Personal'];
const AVAILABLE_TAGS = ['Important', 'Urgent', 'Work', 'Personal', 'Team', 'Client'];

function CalendarSidebarWidget() {
  const appId = runtimeAppIdFromPathname(window.location.pathname);
  const [events, setEvents] = useState<Event[]>([]);
  const [uiState, setUiState] = useState<CalendarUiState>(() => readCalendarUiState(appId));
  const [newEvent, setNewEvent] = useState<DraftEvent>(() => defaultDraft(new Date(), defaultColors, CATEGORIES));
  const [selectedDraft, setSelectedDraft] = useState<Event | null>(null);
  const [error, setError] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const lastCreateRequestId = useRef('');

  const selectedEvent = useMemo(
    () => events.find((event) => event.id === uiState.selectedEventId) || null,
    [events, uiState.selectedEventId],
  );

  async function refreshEvents() {
    try {
      setEvents(await listEvents(appId));
      setError('');
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load Calendar.');
    }
  }

  useEffect(() => {
    void refreshEvents();
  }, [appId]);

  useEffect(() => {
    if (uiState.sidebarMode === 'create' && uiState.requestId !== lastCreateRequestId.current) {
      lastCreateRequestId.current = uiState.requestId;
      setNewEvent(defaultDraft(new Date(), defaultColors, CATEGORIES));
      setSelectedDraft(null);
      setError('');
      return;
    }
    if (uiState.sidebarMode === 'details') {
      setSelectedDraft(selectedEvent ? { ...selectedEvent, tags: [...(selectedEvent.tags || [])] } : null);
      setError('');
    }
  }, [selectedEvent, uiState.requestId, uiState.sidebarMode]);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as { owner_app_id?: string; resource?: string; type?: string };
      if (payload.owner_app_id !== appId && payload.type !== 'maverick.widget.context-changed') {
        return;
      }
      if (payload.type === 'maverick.widget.context-changed') {
        setUiState(readCalendarUiState(appId));
        void refreshEvents();
        return;
      }
      if (payload.type === 'maverick.widget.data-changed') {
        if (payload.resource === CALENDAR_UI_STATE_RESOURCE) {
          setUiState(readCalendarUiState(appId));
        }
        if (payload.resource !== CALENDAR_UI_STATE_RESOURCE) {
          void refreshEvents();
        }
      }
    }
    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, [appId]);

  function updateUiState(patch: Partial<CalendarUiState>, detail: Record<string, unknown> = {}) {
    const next = writeCalendarUiState(appId, patch);
    setUiState(next);
    notifyCalendarUiStateChanged(appId, detail);
  }

  function getColorClasses(colorValue: string) {
    return defaultColors.find((color) => color.value === colorValue) || defaultColors[0];
  }

  function setPanelDraft(patch: DraftEvent) {
    if (uiState.sidebarMode === 'create') {
      setNewEvent((current) => ({ ...current, ...patch }));
      return;
    }
    setSelectedDraft((current) => (current ? { ...current, ...patch } : current));
  }

  function toggleTag(tag: string) {
    const updateTags = (currentTags: string[] = []) => currentTags.includes(tag) ? currentTags.filter((item) => item !== tag) : [...currentTags, tag];
    if (uiState.sidebarMode === 'create') {
      setNewEvent((current) => ({ ...current, tags: updateTags(current.tags) }));
      return;
    }
    setSelectedDraft((current) => (current ? { ...current, tags: updateTags(current.tags) } : current));
  }

  async function submitCreate() {
    const validation = validateDraft(newEvent);
    if (validation) {
      setError(validation);
      return;
    }
    setIsSaving(true);
    setError('');
    try {
      const created = await createEvent(appId, {
        title: newEvent.title!.trim(),
        description: newEvent.description || '',
        startTime: newEvent.startTime!,
        endTime: newEvent.endTime!,
        color: newEvent.color || defaultColors[0].value,
        category: newEvent.category || CATEGORIES[0],
        attendees: newEvent.attendees || [],
        tags: newEvent.tags || [],
      });
      setEvents((current) => [...current.filter((event) => event.id !== created.id), created]);
      updateUiState({ selectedEventId: created.id, sidebarMode: 'details' }, { action: 'created-event', event_id: created.id });
      notifyCalendarDataChanged(appId);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'Event could not be created.');
    } finally {
      setIsSaving(false);
    }
  }

  async function submitUpdate() {
    if (!selectedDraft) {
      return;
    }
    const validation = validateDraft(selectedDraft);
    if (validation) {
      setError(validation);
      return;
    }
    setIsSaving(true);
    setError('');
    try {
      const updated = await updateEvent(appId, selectedDraft.id, selectedDraft);
      setEvents((current) => current.map((event) => (event.id === updated.id ? updated : event)));
      setSelectedDraft(updated);
      notifyCalendarDataChanged(appId);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'Event could not be saved.');
    } finally {
      setIsSaving(false);
    }
  }

  async function submitDelete() {
    if (!selectedDraft) {
      return;
    }
    setIsSaving(true);
    setError('');
    try {
      await deleteEvent(appId, selectedDraft.id, selectedDraft.revision);
      setEvents((current) => current.filter((event) => event.id !== selectedDraft.id));
      updateUiState({ selectedEventId: '', sidebarMode: 'idle' }, { action: 'deleted-event', event_id: selectedDraft.id });
      notifyCalendarDataChanged(appId);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'Event could not be deleted.');
    } finally {
      setIsSaving(false);
    }
  }

  const panelMode = uiState.sidebarMode;
  const panelDraft = panelMode === 'create' ? newEvent : selectedDraft;

  return (
    <main className="calendar-sidebar-widget calendar-board">
      <div className="calendar-sidebar-widget__panel">
        {panelMode === 'idle' ? (
          <div className="calendar-sidebar-widget__empty">
            <span>Choose an event or create a new one.</span>
          </div>
        ) : (
          <EventPanel
            mode={panelMode === 'create' ? 'create' : 'details'}
            draft={panelDraft}
            error={error}
            isSaving={isSaving}
            categories={CATEGORIES}
            colors={defaultColors}
            availableTags={AVAILABLE_TAGS}
            getColorClasses={getColorClasses}
            setDraft={setPanelDraft}
            toggleTag={toggleTag}
            onCreate={submitCreate}
            onUpdate={submitUpdate}
            onDelete={submitDelete}
            onClose={() => updateUiState({ selectedEventId: '', sidebarMode: 'idle' }, { action: 'close-panel' })}
          />
        )}
      </div>
    </main>
  );
}

function notifyCalendarDataChanged(appId: string) {
  window.parent?.postMessage({ type: 'maverick.app.data-changed', owner_app_id: appId, resource: 'events' }, window.location.origin);
}

createRoot(document.getElementById('calendar-sidebar-root') as HTMLElement).render(<CalendarSidebarWidget />);
