"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type SetStateAction,
} from "react";
import { isExactMaverickParentMessage } from "@maverick/pwa-cache";
import {
  CALENDAR_UI_STATE_RESOURCE,
  notifyCalendarUiStateChanged,
  readCalendarUiState,
  writeCalendarUiState,
} from "@/calendar-ui-state";
import { navigateMonth, movedEventTimes } from "./time-layout";
import { t } from "@/preferences";
import { useCalendarPreferences } from "@/useCalendarPreferences";
import { GlobalSearch } from "./global-search";
import { cn } from "@/lib/utils";
import { CalendarBoardViews } from "./calendar-board-views";
import { FilterBar } from "./calendar-filter-bar";
import { Header } from "./calendar-header";
import type { CalendarView, Event, EventManagerProps } from "./calendar-types";
import {
  eventDisplayDate,
  calendarAccountFilterValues,
  calendarAccountOptions,
  defaultColors,
  eventIsReadOnly,
  viewportFromViewState,
  viewStateSignature,
} from "./calendar-utils";

export type { Event, EventManagerProps } from "./calendar-types";

const EMPTY_EVENTS: Event[] = [];

export function EventManager({
  events: initialEvents = EMPTY_EVENTS,
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
  const initialUiState = readCalendarUiState(runtimeAppId);
  const [events, setEvents] = useState<Event[]>(initialEvents);
  const [currentDate, setCurrentDate] = useState(new Date());
  useEffect(() => {
    onVisibleDateChange?.(currentDate);
    writeCalendarUiState(runtimeAppId, { viewDate: currentDate.toISOString() });
  }, [currentDate, onVisibleDateChange]);
  const preferredDefaultView = useMemo<CalendarView>(
    () =>
      window.matchMedia?.("(max-width: 640px)").matches ? "list" : defaultView,
    [defaultView],
  );
  const [view, setView] = useState<CalendarView>(preferredDefaultView);
  const selectedDay = useRef(new Date().getDate());
  useCalendarPreferences();
  const [dropError, setDropError] = useState("");
  const [draggedEvent, setDraggedEvent] = useState<Event | null>(null);
  const [searchQuery, setSearchQueryState] = useState(
    initialUiState.searchQuery,
  );
  const [selectedColors, setSelectedColors] = useState<string[]>(
    initialUiState.selectedColors,
  );
  const [selectedTags, setSelectedTags] = useState<string[]>(
    initialUiState.selectedTags,
  );
  const [selectedCategories, setSelectedCategories] = useState<string[]>(
    initialUiState.selectedCategories,
  );
  const [selectedAccounts, setSelectedAccounts] = useState<string[]>(
    initialUiState.selectedAccounts,
  );
  const handledFocusVersion = useRef(0);
  const handledViewStateSignature = useRef("");

  useEffect(() => {
    setEvents(initialEvents);
  }, [initialEvents]);

  useEffect(() => {
    applyUiState(readCalendarUiState(runtimeAppId));
  }, [runtimeAppId]);

  useEffect(() => {
    function handleUiStateMessage(event: MessageEvent) {
      if (
        !isExactMaverickParentMessage(event) ||
        !event.data ||
        typeof event.data !== "object"
      ) {
        return;
      }
      const payload = event.data as {
        owner_app_id?: string;
        resource?: string;
        type?: string;
      };
      if (
        payload.type === "maverick.app.data-changed" &&
        payload.owner_app_id === runtimeAppId &&
        payload.resource === CALENDAR_UI_STATE_RESOURCE
      ) {
        applyUiState(readCalendarUiState(runtimeAppId));
      }
    }
    window.addEventListener("message", handleUiStateMessage);
    return () => window.removeEventListener("message", handleUiStateMessage);
  }, [runtimeAppId]);

  useEffect(() => {
    if (
      !focusEventId ||
      !focusVersion ||
      handledFocusVersion.current === focusVersion
    ) {
      return;
    }
    const event = events.find((item) => item.id === focusEventId);
    if (!event) {
      return;
    }
    handledFocusVersion.current = focusVersion;
    selectedDay.current = eventDisplayDate(event).getDate();
    setCurrentDate(eventDisplayDate(event));
    setView("day");
    openEventOverlay(event);
  }, [events, focusEventId, focusVersion]);

  useEffect(() => {
    const signature = viewStateSignature(viewState);
    if (signature === handledViewStateSignature.current) {
      return;
    }
    const viewport = viewportFromViewState(
      viewState,
      events,
      preferredDefaultView,
    );
    if (!viewport) {
      return;
    }
    setCurrentDate(viewport.date);
    setView(viewport.view);
    if (!viewport.pendingEventResolution) {
      handledViewStateSignature.current = signature;
    }
  }, [preferredDefaultView, events, viewState]);

  const filteredEvents = useMemo(() => {
    return events.filter((event) => {
      if (searchQuery) {
        const query = searchQuery.toLowerCase();
        const matchesSearch =
          event.title.toLowerCase().includes(query) ||
          event.description?.toLowerCase().includes(query) ||
          event.category?.toLowerCase().includes(query) ||
          event.tags?.some((tag) => tag.toLowerCase().includes(query));
        if (!matchesSearch) return false;
      }
      if (selectedColors.length > 0 && !selectedColors.includes(event.color))
        return false;
      if (
        selectedTags.length > 0 &&
        !event.tags?.some((tag) => selectedTags.includes(tag))
      )
        return false;
      if (
        selectedCategories.length > 0 &&
        (!event.category || !selectedCategories.includes(event.category))
      )
        return false;
      if (
        selectedAccounts.length > 0 &&
        !calendarAccountFilterValues(event).some((value) =>
          selectedAccounts.includes(value),
        )
      )
        return false;
      return true;
    });
  }, [
    events,
    searchQuery,
    selectedColors,
    selectedTags,
    selectedCategories,
    selectedAccounts,
  ]);

  const accountOptions = useMemo(
    () => calendarAccountOptions(events, calendarConnections),
    [events, calendarConnections],
  );
  const hasActiveFilters =
    selectedColors.length > 0 ||
    selectedTags.length > 0 ||
    selectedCategories.length > 0 ||
    selectedAccounts.length > 0;

  const openEvent = useCallback(
    (event: Event) => {
      openEventOverlay(event);
      onEventOpen?.(event);
    },
    [onEventOpen, runtimeAppId],
  );
  const handleDragStart = useCallback(
    (event: Event) => {
      if (eventIsReadOnly(event, calendars)) {
        setDraggedEvent(null);
        return;
      }
      setDraggedEvent(event);
    },
    [calendars],
  );

  const handleDrop = useCallback(
    async (date: Date, hour?: number) => {
      if (!draggedEvent) return;
      const updatedEvent = {
        ...draggedEvent,
        ...movedEventTimes(draggedEvent, date, hour),
      };
      const previousEvents = events;
      try {
        setEvents((prev) =>
          prev.map((event) =>
            event.id === draggedEvent.id ? updatedEvent : event,
          ),
        );
        await onEventUpdate?.(draggedEvent.id, updatedEvent);
      } catch (error) {
        setEvents(previousEvents);
        setDropError(
          error instanceof Error
            ? error.message
            : t("Event could not be saved."),
        );
      } finally {
        setDraggedEvent(null);
      }
    },
    [draggedEvent, events, onEventUpdate],
  );

  const navigateDate = useCallback(
    (direction: "prev" | "next") => {
      setCurrentDate((prev) => {
        const nextDate = new Date(prev);
        if (view === "month")
          return navigateMonth(
            prev,
            direction === "next" ? 1 : -1,
            selectedDay.current,
          );
        if (view === "week")
          nextDate.setDate(prev.getDate() + (direction === "next" ? 7 : -7));
        if (view === "day")
          nextDate.setDate(prev.getDate() + (direction === "next" ? 1 : -1));
        if (view === "list")
          nextDate.setDate(prev.getDate() + (direction === "next" ? 1 : -1));
        return nextDate;
      });
    },
    [view],
  );

  const getColorClasses = useCallback(
    (colorValue: string) =>
      colors.find((color) => color.value === colorValue) || colors[0],
    [colors],
  );

  function applyUiState(uiState: ReturnType<typeof readCalendarUiState>) {
    setSearchQueryState(uiState.searchQuery);
    setSelectedColors(uiState.selectedColors);
    setSelectedTags(uiState.selectedTags);
    setSelectedCategories(uiState.selectedCategories);
    setSelectedAccounts(uiState.selectedAccounts);
  }

  function setSearchQuery(value: string) {
    const next = writeCalendarUiState(runtimeAppId, { searchQuery: value });
    applyUiState(next);
    notifyCalendarUiStateChanged(runtimeAppId, { action: "search" });
  }

  function updateColorFilters(value: SetStateAction<string[]>) {
    const nextSelectedColors =
      typeof value === "function" ? value(selectedColors) : value;
    const next = writeCalendarUiState(runtimeAppId, {
      selectedColors: nextSelectedColors,
    });
    applyUiState(next);
    notifyCalendarUiStateChanged(runtimeAppId, { action: "filter-colors" });
  }

  function updateTagFilters(value: SetStateAction<string[]>) {
    const nextSelectedTags =
      typeof value === "function" ? value(selectedTags) : value;
    const next = writeCalendarUiState(runtimeAppId, {
      selectedTags: nextSelectedTags,
    });
    applyUiState(next);
    notifyCalendarUiStateChanged(runtimeAppId, { action: "filter-tags" });
  }

  function updateCategoryFilters(value: SetStateAction<string[]>) {
    const nextSelectedCategories =
      typeof value === "function" ? value(selectedCategories) : value;
    const next = writeCalendarUiState(runtimeAppId, {
      selectedCategories: nextSelectedCategories,
    });
    applyUiState(next);
    notifyCalendarUiStateChanged(runtimeAppId, { action: "filter-categories" });
  }

  function updateAccountFilters(value: SetStateAction<string[]>) {
    const nextSelectedAccounts =
      typeof value === "function" ? value(selectedAccounts) : value;
    const next = writeCalendarUiState(runtimeAppId, {
      selectedAccounts: nextSelectedAccounts,
    });
    applyUiState(next);
    notifyCalendarUiStateChanged(runtimeAppId, { action: "filter-accounts" });
  }

  function clearFilters() {
    const next = writeCalendarUiState(runtimeAppId, {
      selectedColors: [],
      selectedTags: [],
      selectedCategories: [],
      selectedAccounts: [],
    });
    applyUiState(next);
    notifyCalendarUiStateChanged(runtimeAppId, { action: "clear-filters" });
  }

  function openEventOverlay(event: Event) {
    writeCalendarUiState(runtimeAppId, {
      selectedEventId: event.id,
      sidebarMode: "details",
    });
    notifyCalendarUiStateChanged(runtimeAppId, {
      action: "open-event",
      event_id: event.id,
    });
  }

  function createAt(date: Date, hour?: number) {
    const start = new Date(date);
    start.setHours(
      hour === undefined ? 9 : Math.floor(hour),
      hour === undefined ? 0 : Math.round((hour % 1) * 60),
      0,
      0,
    );
    writeCalendarUiState(runtimeAppId, {
      sidebarMode: "create",
      selectedEventId: "",
      createStart: start.toISOString(),
    });
    notifyCalendarUiStateChanged(runtimeAppId, { action: "new-event" });
  }
  function openDay(date: Date) {
    selectedDay.current = date.getDate();
    setCurrentDate(date);
    setView("day");
  }
  return (
    <div className={cn("flex flex-col gap-4", className)}>
      {dropError && <div role="alert">{dropError}</div>}
      <Header
        onCreate={() => createAt(currentDate)}
        view={view}
        currentDate={currentDate}
        setView={setView}
        navigateDate={navigateDate}
        setToday={() => {
          selectedDay.current = new Date().getDate();
          setCurrentDate(new Date());
        }}
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
      {searchQuery.trim() ? (
        <GlobalSearch
          appId={runtimeAppId}
          query={searchQuery}
          onSelect={(event) => {
            setSearchQuery("");
            setEvents((current) => [
              ...current.filter((e) => e.id !== event.id),
              event,
            ]);
            openDay(eventDisplayDate(event));
            openEvent(event);
          }}
        />
      ) : (
        <CalendarBoardViews
          onCreateAt={createAt}
          onDayOpen={openDay}
          currentDate={currentDate}
          events={filteredEvents}
          getColorClasses={getColorClasses}
          onDrop={handleDrop}
          onEventClick={openEvent}
          onDragStart={handleDragStart}
          onDragEnd={() => setDraggedEvent(null)}
          view={view}
        />
      )}
    </div>
  );
}
