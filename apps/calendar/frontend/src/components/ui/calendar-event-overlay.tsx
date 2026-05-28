import { useEffect, useMemo, useRef, useState } from "react"
import {
  CALENDAR_UI_STATE_CHANGED_EVENT,
  CALENDAR_UI_STATE_RESOURCE,
  notifyCalendarUiStateChanged,
  readCalendarUiState,
  writeCalendarUiState,
  type CalendarUiState,
} from "@/calendar-ui-state"
import type { CalendarConnection, CalendarRemoteCalendar, DraftEvent, Event } from "./calendar-types"
import { calendarSourceOptions, defaultColors, defaultDraft, validateDraft } from "./calendar-utils"
import { EventPanel } from "./calendar-event-panel"

type CalendarEventOverlayProps = {
  runtimeAppId: string
  events: Event[]
  connections: CalendarConnection[]
  calendars: CalendarRemoteCalendar[]
  categories: string[]
  availableTags: string[]
  onCreateEvent: (event: Omit<Event, "id">) => Promise<Event>
  onUpdateEvent: (id: string, event: Partial<Event>) => Promise<Event>
  onDeleteEvent: (event: Event) => Promise<void>
}

export function CalendarEventOverlay({
  runtimeAppId,
  events,
  connections,
  calendars,
  categories,
  availableTags,
  onCreateEvent,
  onUpdateEvent,
  onDeleteEvent,
}: CalendarEventOverlayProps) {
  const [uiState, setUiState] = useState<CalendarUiState>(() => readCalendarUiState(runtimeAppId))
  const [newEvent, setNewEvent] = useState<DraftEvent>(() => defaultDraft(new Date(), defaultColors, categories))
  const [selectedDraft, setSelectedDraft] = useState<Event | null>(null)
  const [error, setError] = useState("")
  const [isSaving, setIsSaving] = useState(false)
  const lastCreateRequestId = useRef("")

  const selectedEvent = useMemo(
    () => events.find((event) => event.id === uiState.selectedEventId) || null,
    [events, uiState.selectedEventId],
  )
  const sourceOptions = useMemo(() => calendarSourceOptions(events, connections, calendars), [events, connections, calendars])

  useEffect(() => {
    setUiState(readCalendarUiState(runtimeAppId))
  }, [runtimeAppId])

  useEffect(() => {
    if (uiState.sidebarMode === "create" && uiState.requestId !== lastCreateRequestId.current) {
      lastCreateRequestId.current = uiState.requestId
      setNewEvent(defaultDraft(new Date(), defaultColors, categories))
      setSelectedDraft(null)
      setError("")
      return
    }
    if (uiState.sidebarMode === "details") {
      setSelectedDraft(selectedEvent ? { ...selectedEvent, tags: [...(selectedEvent.tags || [])] } : null)
      setError("")
    }
  }, [categories, selectedEvent, uiState.requestId, uiState.sidebarMode])

  useEffect(() => {
    function readLatestUiState() {
      setUiState(readCalendarUiState(runtimeAppId))
    }

    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
        return
      }
      const payload = event.data as { owner_app_id?: string; resource?: string; type?: string }
      if (
        payload.type === "maverick.app.data-changed" &&
        payload.owner_app_id === runtimeAppId &&
        payload.resource === CALENDAR_UI_STATE_RESOURCE
      ) {
        readLatestUiState()
      }
    }

    function handleLocalUiStateChange() {
      readLatestUiState()
    }

    function handleStorageChange(event: StorageEvent) {
      if (!event.key || event.key.includes(`.${runtimeAppId}`)) {
        readLatestUiState()
      }
    }

    window.addEventListener("message", handleShellMessage)
    window.addEventListener(CALENDAR_UI_STATE_CHANGED_EVENT, handleLocalUiStateChange)
    window.addEventListener("storage", handleStorageChange)
    return () => {
      window.removeEventListener("message", handleShellMessage)
      window.removeEventListener(CALENDAR_UI_STATE_CHANGED_EVENT, handleLocalUiStateChange)
      window.removeEventListener("storage", handleStorageChange)
    }
  }, [runtimeAppId])

  useEffect(() => {
    if (uiState.sidebarMode !== "create" && uiState.sidebarMode !== "details") {
      return undefined
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        closeOverlay()
      }
    }
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [uiState.sidebarMode])

  function updateUiState(patch: Partial<CalendarUiState>, detail: Record<string, unknown> = {}) {
    const next = writeCalendarUiState(runtimeAppId, patch)
    setUiState(next)
    notifyCalendarUiStateChanged(runtimeAppId, detail)
  }

  function getColorClasses(colorValue: string) {
    return defaultColors.find((color) => color.value === colorValue) || defaultColors[0]
  }

  function setPanelDraft(patch: DraftEvent) {
    if (uiState.sidebarMode === "create") {
      setNewEvent((current) => ({ ...current, ...patch }))
      return
    }
    setSelectedDraft((current) => (current ? { ...current, ...patch } : current))
  }

  function toggleTag(tag: string) {
    const updateTags = (currentTags: string[] = []) =>
      currentTags.includes(tag) ? currentTags.filter((item) => item !== tag) : [...currentTags, tag]
    if (uiState.sidebarMode === "create") {
      setNewEvent((current) => ({ ...current, tags: updateTags(current.tags) }))
      return
    }
    setSelectedDraft((current) => (current ? { ...current, tags: updateTags(current.tags) } : current))
  }

  async function submitCreate() {
    const validation = validateDraft(newEvent)
    if (validation) {
      setError(validation)
      return
    }
    setIsSaving(true)
    setError("")
    try {
      const created = await onCreateEvent({
        title: newEvent.title!.trim(),
        description: newEvent.description || "",
        startTime: newEvent.startTime!,
        endTime: newEvent.endTime!,
        color: newEvent.color || defaultColors[0].value,
        category: newEvent.category || categories[0],
        attendees: newEvent.attendees || [],
        tags: newEvent.tags || [],
        source: newEvent.source || "calendar",
        external_refs: newEvent.external_refs || {},
      })
      setSelectedDraft(created)
      updateUiState({ selectedEventId: "", sidebarMode: "idle" }, { action: "created-event", event_id: created.id })
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Event could not be created.")
    } finally {
      setIsSaving(false)
    }
  }

  async function submitUpdate() {
    if (!selectedDraft) {
      return
    }
    const validation = validateDraft(selectedDraft)
    if (validation) {
      setError(validation)
      return
    }
    setIsSaving(true)
    setError("")
    try {
      const updated = await onUpdateEvent(selectedDraft.id, selectedDraft)
      setSelectedDraft(updated)
      updateUiState({ selectedEventId: "", sidebarMode: "idle" }, { action: "updated-event", event_id: updated.id })
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Event could not be saved.")
    } finally {
      setIsSaving(false)
    }
  }

  async function submitDelete() {
    if (!selectedDraft) {
      return
    }
    setIsSaving(true)
    setError("")
    try {
      await onDeleteEvent(selectedDraft)
      updateUiState({ selectedEventId: "", sidebarMode: "idle" }, { action: "deleted-event", event_id: selectedDraft.id })
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Event could not be deleted.")
    } finally {
      setIsSaving(false)
    }
  }

  function closeOverlay() {
    updateUiState({ selectedEventId: "", sidebarMode: "idle" }, { action: "close-panel" })
  }

  if (uiState.sidebarMode !== "create" && uiState.sidebarMode !== "details") {
    return null
  }

  const panelDraft = uiState.sidebarMode === "create" ? newEvent : selectedDraft

  return (
    <div
      className="calendar-event-overlay"
      role="dialog"
      aria-modal="true"
      aria-label={uiState.sidebarMode === "create" ? "Create event" : "Event details"}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          closeOverlay()
        }
      }}
    >
      <div className="calendar-event-overlay__panel">
        <EventPanel
          mode={uiState.sidebarMode === "create" ? "create" : "details"}
          draft={panelDraft}
          error={error}
          isSaving={isSaving}
          categories={categories}
          colors={defaultColors}
          availableTags={availableTags}
          calendars={calendars}
          calendarSourceOptions={sourceOptions}
          getColorClasses={getColorClasses}
          setDraft={setPanelDraft}
          toggleTag={toggleTag}
          onCreate={submitCreate}
          onUpdate={submitUpdate}
          onDelete={submitDelete}
          onClose={closeOverlay}
        />
      </div>
    </div>
  )
}
