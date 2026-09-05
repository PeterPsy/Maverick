"use client"

import { useCallback, useEffect, useMemo, useRef, useState, type SetStateAction } from "react"
import { CALENDAR_UI_STATE_RESOURCE, notifyCalendarUiStateChanged, readCalendarUiState, writeCalendarUiState } from "@/calendar-ui-state"
import { cn } from "@/lib/utils"
import { CalendarBoardViews } from "./calendar-board-views"
import { FilterBar } from "./calendar-filter-bar"
import { Header } from "./calendar-header"
import type { CalendarView, Event, EventManagerProps } from "./calendar-types"
import { calendarAccountFilterValues, calendarAccountOptions, defaultColors, eventIsReadOnly, viewportFromViewState, viewStateSignature } from "./calendar-utils"

export type { Event, EventManagerProps } from "./calendar-types"

export function EventManager({
  events: initialEvents = [],
  onVisibleDateChange,
  onEventUpdate,
  colors = defaultColors,
  categories = [],
  availableTags = [],
  defaultView = "month",
  className,
  focusEventId = "",
  focusVersion = 0,
  viewState,
  onEventOpen,
  runtimeAppId = "calendar",
  calendarConnections = [],
  calendars = [],
  onSyncConnections,
  isSyncingConnections = false,
}: EventManagerProps) {
  const initialUiState = readCalendarUiState(runtimeAppId)
  const [events, setEvents] = useState<Event[]>(initialEvents)
  const [currentDate, setCurrentDate] = useState(new Date())
  useEffect(() => { onVisibleDateChange?.(currentDate) }, [currentDate, onVisibleDateChange])
  const [view, setView] = useState<CalendarView>(defaultView)
  const [draggedEvent, setDraggedEvent] = useState<Event | null>(null)
  const [searchQuery, setSearchQueryState] = useState(initialUiState.searchQuery)
  const [selectedColors, setSelectedColors] = useState<string[]>(initialUiState.selectedColors)
  const [selectedTags, setSelectedTags] = useState<string[]>(initialUiState.selectedTags)
  const [selectedCategories, setSelectedCategories] = useState<string[]>(initialUiState.selectedCategories)
  const [selectedAccounts, setSelectedAccounts] = useState<string[]>(initialUiState.selectedAccounts)
  const handledFocusVersion = useRef(0)
  const handledViewStateSignature = useRef("")

  useEffect(() => {
    setEvents(initialEvents)
  }, [initialEvents])

  useEffect(() => {
    applyUiState(readCalendarUiState(runtimeAppId))
  }, [runtimeAppId])

  useEffect(() => {
    function handleUiStateMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
        return
      }
      const payload = event.data as { owner_app_id?: string; resource?: string; type?: string }
      if (payload.type === "maverick.app.data-changed" && payload.owner_app_id === runtimeAppId && payload.resource === CALENDAR_UI_STATE_RESOURCE) {
        applyUiState(readCalendarUiState(runtimeAppId))
      }
    }
    window.addEventListener("message", handleUiStateMessage)
    return () => window.removeEventListener("message", handleUiStateMessage)
  }, [runtimeAppId])

  useEffect(() => {
    if (!focusEventId || !focusVersion || handledFocusVersion.current === focusVersion) {
      return
    }
    const event = events.find((item) => item.id === focusEventId)
    if (!event) {
      return
    }
    handledFocusVersion.current = focusVersion
    setCurrentDate(event.startTime)
    setView("day")
    openEventOverlay(event)
  }, [events, focusEventId, focusVersion])

  useEffect(() => {
    const signature = viewStateSignature(viewState)
    if (signature === handledViewStateSignature.current) {
      return
    }
    const viewport = viewportFromViewState(viewState, events, defaultView)
    if (!viewport) {
      return
    }
    setCurrentDate(viewport.date)
    setView(viewport.view)
    if (!viewport.pendingEventResolution) {
      handledViewStateSignature.current = signature
    }
  }, [defaultView, events, viewState])

  const filteredEvents = useMemo(() => {
    return events.filter((event) => {
      if (searchQuery) {
        const query = searchQuery.toLowerCase()
        const matchesSearch =
          event.title.toLowerCase().includes(query) ||
          event.description?.toLowerCase().includes(query) ||
          event.category?.toLowerCase().includes(query) ||
          event.tags?.some((tag) => tag.toLowerCase().includes(query))
        if (!matchesSearch) return false
      }
      if (selectedColors.length > 0 && !selectedColors.includes(event.color)) return false
      if (selectedTags.length > 0 && !event.tags?.some((tag) => selectedTags.includes(tag))) return false
      if (selectedCategories.length > 0 && (!event.category || !selectedCategories.includes(event.category))) return false
      if (selectedAccounts.length > 0 && !calendarAccountFilterValues(event).some((value) => selectedAccounts.includes(value))) return false
      return true
    })
  }, [events, searchQuery, selectedColors, selectedTags, selectedCategories, selectedAccounts])

  const accountOptions = useMemo(() => calendarAccountOptions(events, calendarConnections), [events, calendarConnections])
  const hasActiveFilters =
    selectedColors.length > 0 || selectedTags.length > 0 || selectedCategories.length > 0 || selectedAccounts.length > 0

  const openEvent = useCallback(
    (event: Event) => {
      openEventOverlay(event)
      onEventOpen?.(event)
    },
    [onEventOpen, runtimeAppId],
  )
  const handleDragStart = useCallback(
    (event: Event) => {
      if (eventIsReadOnly(event, calendars)) {
        setDraggedEvent(null)
        return
      }
      setDraggedEvent(event)
    },
    [calendars],
  )

  const handleDrop = useCallback(
    async (date: Date, hour?: number) => {
      if (!draggedEvent) return
      const duration = draggedEvent.endTime.getTime() - draggedEvent.startTime.getTime()
      const newStartTime = new Date(date)
      if (hour !== undefined) newStartTime.setHours(hour, 0, 0, 0)
      const updatedEvent = {
        ...draggedEvent,
        startTime: newStartTime,
        endTime: new Date(newStartTime.getTime() + duration),
      }
      const previousEvents = events
      try {
        setEvents((prev) => prev.map((event) => (event.id === draggedEvent.id ? updatedEvent : event)))
        await onEventUpdate?.(draggedEvent.id, updatedEvent)
      } catch (error) {
        setEvents(previousEvents)
      } finally {
        setDraggedEvent(null)
      }
    },
    [draggedEvent, events, onEventUpdate],
  )

  const navigateDate = useCallback(
    (direction: "prev" | "next") => {
      setCurrentDate((prev) => {
        const nextDate = new Date(prev)
        if (view === "month") nextDate.setMonth(prev.getMonth() + (direction === "next" ? 1 : -1))
        if (view === "week") nextDate.setDate(prev.getDate() + (direction === "next" ? 7 : -7))
        if (view === "day") nextDate.setDate(prev.getDate() + (direction === "next" ? 1 : -1))
        if (view === "list") nextDate.setDate(prev.getDate() + (direction === "next" ? 1 : -1))
        return nextDate
      })
    },
    [view],
  )

  const getColorClasses = useCallback(
    (colorValue: string) => colors.find((color) => color.value === colorValue) || colors[0],
    [colors],
  )

  function applyUiState(uiState: ReturnType<typeof readCalendarUiState>) {
    setSearchQueryState(uiState.searchQuery)
    setSelectedColors(uiState.selectedColors)
    setSelectedTags(uiState.selectedTags)
    setSelectedCategories(uiState.selectedCategories)
    setSelectedAccounts(uiState.selectedAccounts)
  }

  function setSearchQuery(value: string) {
    const next = writeCalendarUiState(runtimeAppId, { searchQuery: value })
    applyUiState(next)
    notifyCalendarUiStateChanged(runtimeAppId, { action: "search" })
  }

  function updateColorFilters(value: SetStateAction<string[]>) {
    const nextSelectedColors = typeof value === "function" ? value(selectedColors) : value
    const next = writeCalendarUiState(runtimeAppId, { selectedColors: nextSelectedColors })
    applyUiState(next)
    notifyCalendarUiStateChanged(runtimeAppId, { action: "filter-colors" })
  }

  function updateTagFilters(value: SetStateAction<string[]>) {
    const nextSelectedTags = typeof value === "function" ? value(selectedTags) : value
    const next = writeCalendarUiState(runtimeAppId, { selectedTags: nextSelectedTags })
    applyUiState(next)
    notifyCalendarUiStateChanged(runtimeAppId, { action: "filter-tags" })
  }

  function updateCategoryFilters(value: SetStateAction<string[]>) {
    const nextSelectedCategories = typeof value === "function" ? value(selectedCategories) : value
    const next = writeCalendarUiState(runtimeAppId, { selectedCategories: nextSelectedCategories })
    applyUiState(next)
    notifyCalendarUiStateChanged(runtimeAppId, { action: "filter-categories" })
  }

  function updateAccountFilters(value: SetStateAction<string[]>) {
    const nextSelectedAccounts = typeof value === "function" ? value(selectedAccounts) : value
    const next = writeCalendarUiState(runtimeAppId, { selectedAccounts: nextSelectedAccounts })
    applyUiState(next)
    notifyCalendarUiStateChanged(runtimeAppId, { action: "filter-accounts" })
  }

  function clearFilters() {
    const next = writeCalendarUiState(runtimeAppId, {
      selectedColors: [],
      selectedTags: [],
      selectedCategories: [],
      selectedAccounts: [],
    })
    applyUiState(next)
    notifyCalendarUiStateChanged(runtimeAppId, { action: "clear-filters" })
  }

  function openEventOverlay(event: Event) {
    writeCalendarUiState(runtimeAppId, { selectedEventId: event.id, sidebarMode: "details" })
    notifyCalendarUiStateChanged(runtimeAppId, { action: "open-event", event_id: event.id })
  }

  return (
    <div className={cn("flex flex-col gap-4", className)}>
      <Header
        view={view}
        currentDate={currentDate}
        setView={setView}
        navigateDate={navigateDate}
        setToday={() => setCurrentDate(new Date())}
        searchQuery={searchQuery}
        setSearchQuery={setSearchQuery}
        filters={
          <FilterBar
            searchQuery={searchQuery}
            setSearchQuery={setSearchQuery}
            colors={colors}
            categories={categories}
            availableTags={availableTags}
            accountOptions={accountOptions}
            onSyncConnections={onSyncConnections}
            isSyncingConnections={isSyncingConnections}
            selectedColors={selectedColors}
            selectedTags={selectedTags}
            selectedCategories={selectedCategories}
            selectedAccounts={selectedAccounts}
            setSelectedColors={updateColorFilters}
            setSelectedTags={updateTagFilters}
            setSelectedCategories={updateCategoryFilters}
            setSelectedAccounts={updateAccountFilters}
            hasActiveFilters={hasActiveFilters}
            clearFilters={clearFilters}
            getColorClasses={getColorClasses}
            showSearch={false}
            showAccountFilters={false}
          />
        }
      />
      <CalendarBoardViews
        currentDate={currentDate}
        events={filteredEvents}
        getColorClasses={getColorClasses}
        onDrop={handleDrop}
        onEventClick={openEvent}
        onDragStart={handleDragStart}
        onDragEnd={() => setDraggedEvent(null)}
        view={view}
      />
    </div>
  )
}
