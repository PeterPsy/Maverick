import { CalendarApiError, getFullEvent } from "@/api";
import { t } from "@/preferences";
import { FindTime } from "./find-time";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  isExactMaverickParentMessage,
  observeMaverickVisibility,
} from "@maverick/pwa-cache";
import {
  CALENDAR_UI_STATE_CHANGED_EVENT,
  CALENDAR_UI_STATE_RESOURCE,
  notifyCalendarUiStateChanged,
  readCalendarUiState,
  writeCalendarUiState,
  type CalendarUiState,
} from "@/calendar-ui-state";
import type {
  CalendarConnection,
  CalendarRemoteCalendar,
  DraftEvent,
  Event,
} from "./calendar-types";
import {
  calendarSourceOptions,
  defaultColors,
  defaultDraft,
  validateDraft,
} from "./calendar-utils";
import { EventPanel } from "./calendar-event-panel";

type CalendarEventOverlayProps = {
  runtimeAppId: string;
  events: Event[];
  connections: CalendarConnection[];
  calendars: CalendarRemoteCalendar[];
  categories: string[];
  availableTags: string[];
  onCreateEvent: (event: Omit<Event, "id">) => Promise<Event>;
  onUpdateEvent: (id: string, event: Partial<Event>) => Promise<Event>;
  onDeleteEvent: (event: Event) => Promise<void>;
};

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
  const [uiState, setUiState] = useState<CalendarUiState>(() =>
    readCalendarUiState(runtimeAppId),
  );
  const [newEvent, setNewEvent] = useState<DraftEvent>(() =>
    defaultDraft(new Date(), defaultColors, categories),
  );
  const [selectedDraft, setSelectedDraft] = useState<Event | null>(null);
  const [error, setError] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const dirty = useRef(false);
  const changedFields = useRef(new Set<string>());
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [detailsAvailable, setDetailsAvailable] = useState(false);
  const savingRef = useRef(isSaving);
  savingRef.current = isSaving;
  const draftRef = useRef(selectedDraft);
  draftRef.current = selectedDraft;
  const uiStateRef = useRef(uiState);
  uiStateRef.current = uiState;
  const closeRef = useRef(() => {});
  closeRef.current = closeOverlay;
  const loadedId = useRef("");
  const dialogRef = useRef<HTMLDivElement>(null);
  const [revisionConflict, setRevisionConflict] = useState(false);
  const latestEvent = useRef<Event | null>(null);
  const [conflicts, setConflicts] = useState<
    Array<{ title: string; startTime: string; endTime: string }>
  >([]);

  const selectedEvent = useMemo(
    () => events.find((event) => event.id === uiState.selectedEventId) || null,
    [events, uiState.selectedEventId],
  );
  const sourceOptions = useMemo(
    () => calendarSourceOptions(events, connections, calendars),
    [events, connections, calendars],
  );

  useEffect(() => {
    setUiState(readCalendarUiState(runtimeAppId));
  }, [runtimeAppId]);

  useEffect(() => {
    if (uiState.sidebarMode === "create" && loadedId.current !== "__create__") {
      loadedId.current = "__create__";
      const draft = defaultDraft(
        uiState.createStart ? new Date(uiState.createStart) : new Date(),
        defaultColors,
        categories,
      );
      if (uiState.createStart) {
        draft.startTime = new Date(uiState.createStart);
        draft.endTime = new Date(draft.startTime.getTime() + 3600000);
      }
      draft.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
      draft.idempotency_key = `ui:${uiState.requestId}`;
      setNewEvent(draft);
      setSelectedDraft(null);
      setError("");
      dirty.current = false;
      changedFields.current.clear();
      setRevisionConflict(false);
    }
    if (uiState.sidebarMode === "details" && selectedEvent) {
      latestEvent.current = selectedEvent;
      if (loadedId.current !== selectedEvent.id || !dirty.current) {
        loadedId.current = selectedEvent.id;
        setSelectedDraft((current) =>
          current?.id === selectedEvent.id &&
          current.revision === selectedEvent.revision
            ? { ...selectedEvent, ...current }
            : { ...selectedEvent, tags: [...(selectedEvent.tags || [])] },
        );
        dirty.current = false;
        changedFields.current.clear();
        setError("");
        setRevisionConflict(false);
      } else if (draftRef.current?.revision !== selectedEvent.revision)
        setRevisionConflict(true);
    }
    if (uiState.sidebarMode === "idle") {
      loadedId.current = "";
      dirty.current = false;
    }
  }, [selectedEvent, uiState.requestId, uiState.sidebarMode]);

  useEffect(() => {
    if (
      uiState.sidebarMode !== "details" ||
      !uiState.selectedEventId ||
      navigator.onLine === false
    )
      return;
    let controller: AbortController | undefined;
    const stop = observeMaverickVisibility((visible) => {
      controller?.abort();
      if (!visible) return;
      setLoadingDetails(true);
      setDetailsAvailable(false);
      controller = new AbortController();
      const read = controller;
      void getFullEvent(runtimeAppId, uiState.selectedEventId, read.signal)
        .then((event) => {
          if (read.signal.aborted) return;
          setLoadingDetails(false);
          setDetailsAvailable(Boolean(event));
          if (!event) {
            setError(t("Unable to load event"));
            return;
          }
          latestEvent.current = event;
          if (!dirty.current) setSelectedDraft(event);
          else {
            setRevisionConflict(
              (current) =>
                current || event.revision !== draftRef.current?.revision,
            );
            setSelectedDraft((current) =>
              current
                ? {
                    ...event,
                    ...Object.fromEntries(
                      [...changedFields.current].map((key) => [
                        key,
                        (current as unknown as Record<string, unknown>)[key],
                      ]),
                    ),
                    revision: current.revision,
                  }
                : event,
            );
          }
        })
        .catch((err) => {
          if (!read.signal.aborted) {
            setLoadingDetails(false);
            setDetailsAvailable(false);
            setError(
              err instanceof Error ? err.message : t("Unable to load event"),
            );
          }
        });
    });
    return () => {
      stop();
      controller?.abort();
    };
  }, [
    runtimeAppId,
    uiState.selectedEventId,
    uiState.sidebarMode,
    selectedEvent?.revision,
  ]);

  useEffect(() => {
    function readLatestUiState() {
      const next = readCalendarUiState(runtimeAppId);
      const previous = uiStateRef.current;
      const switchesDraft =
        next.sidebarMode !== previous.sidebarMode ||
        next.selectedEventId !== previous.selectedEventId ||
        (next.sidebarMode === "create" &&
          next.requestId !== previous.requestId);
      if (
        switchesDraft &&
        (savingRef.current ||
          (dirty.current && !window.confirm(t("Discard unsaved changes?"))))
      ) {
        writeCalendarUiState(runtimeAppId, previous);
        return;
      }
      if (switchesDraft) {
        loadedId.current = "";
        dirty.current = false;
        changedFields.current.clear();
        setConflicts([]);
      }
      setUiState(next);
    }

    function handleShellMessage(event: MessageEvent) {
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
        readLatestUiState();
      }
    }

    function handleLocalUiStateChange() {
      readLatestUiState();
    }

    function handleStorageChange(event: StorageEvent) {
      if (!event.key || event.key.includes(`.${runtimeAppId}`)) {
        readLatestUiState();
      }
    }

    window.addEventListener("message", handleShellMessage);
    window.addEventListener(
      CALENDAR_UI_STATE_CHANGED_EVENT,
      handleLocalUiStateChange,
    );
    window.addEventListener("storage", handleStorageChange);
    return () => {
      window.removeEventListener("message", handleShellMessage);
      window.removeEventListener(
        CALENDAR_UI_STATE_CHANGED_EVENT,
        handleLocalUiStateChange,
      );
      window.removeEventListener("storage", handleStorageChange);
    };
  }, [runtimeAppId]);

  useEffect(() => {
    if (uiState.sidebarMode !== "create" && uiState.sidebarMode !== "details")
      return;
    const previous = document.activeElement as HTMLElement | null;
    dialogRef.current?.querySelector<HTMLElement>("input, button")?.focus();
    function keyDown(event: KeyboardEvent) {
      if (event.defaultPrevented) return;
      if (event.key === "Escape") {
        event.preventDefault();
        closeRef.current();
      }
      if (event.key !== "Tab") return;
      if (
        document.activeElement?.closest(
          '[role="listbox"], [data-radix-popper-content-wrapper]',
        )
      )
        return;
      const elements = Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(
          'input:not(:disabled), button:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex="0"]',
        ) || [],
      ).filter((e) => e.getClientRects().length);
      if (!elements.length) return;
      const first = elements[0],
        last = elements.at(-1)!;
      if (!dialogRef.current?.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
        return;
      }
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    function beforeUnload(event: BeforeUnloadEvent) {
      if (dirty.current) {
        event.preventDefault();
        event.returnValue = "";
      }
    }
    window.addEventListener("keydown", keyDown);
    window.addEventListener("beforeunload", beforeUnload);
    return () => {
      window.removeEventListener("keydown", keyDown);
      window.removeEventListener("beforeunload", beforeUnload);
      previous?.focus();
    };
  }, [uiState.sidebarMode]);
  useEffect(() => {
    const listener = (event: Event) =>
      setConflicts((event as unknown as CustomEvent).detail);
    window.addEventListener(
      "calendar-conflicts",
      listener as unknown as EventListener,
    );
    return () =>
      window.removeEventListener(
        "calendar-conflicts",
        listener as unknown as EventListener,
      );
  }, []);

  function updateUiState(
    patch: Partial<CalendarUiState>,
    detail: Record<string, unknown> = {},
  ) {
    const next = writeCalendarUiState(runtimeAppId, patch);
    setUiState(next);
    notifyCalendarUiStateChanged(runtimeAppId, detail);
  }

  function getColorClasses(colorValue: string) {
    return (
      defaultColors.find((color) => color.value === colorValue) ||
      defaultColors[0]
    );
  }

  function setPanelDraft(patch: DraftEvent) {
    dirty.current = true;
    Object.keys(patch).forEach((key) => changedFields.current.add(key));
    if (uiState.sidebarMode === "create") {
      setNewEvent((current) => ({ ...current, ...patch }));
      return;
    }
    setSelectedDraft((current) =>
      current ? { ...current, ...patch } : current,
    );
  }

  function toggleTag(tag: string) {
    dirty.current = true;
    changedFields.current.add("tags");
    const updateTags = (currentTags: string[] = []) =>
      currentTags.includes(tag)
        ? currentTags.filter((item) => item !== tag)
        : [...currentTags, tag];
    if (uiState.sidebarMode === "create") {
      setNewEvent((current) => ({
        ...current,
        tags: updateTags(current.tags),
      }));
      return;
    }
    setSelectedDraft((current) =>
      current ? { ...current, tags: updateTags(current.tags) } : current,
    );
  }

  async function submitCreate() {
    const validation = validateDraft(newEvent);
    if (validation) {
      setError(validation);
      return;
    }
    setIsSaving(true);
    setError("");
    try {
      const created = await onCreateEvent({
        ...newEvent,
        title: newEvent.title!.trim(),
        startTime: newEvent.startTime!,
        endTime: newEvent.endTime!,
        color: newEvent.color || defaultColors[0].value,
      });
      dirty.current = false;
      setSelectedDraft(created);
      updateUiState(
        { selectedEventId: "", sidebarMode: "idle" },
        { action: "created-event", event_id: created.id },
      );
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : "Event could not be created.",
      );
    } finally {
      setIsSaving(false);
    }
  }

  async function submitUpdate() {
    if (!selectedDraft || loadingDetails || !detailsAvailable) {
      return;
    }
    const validation = validateDraft(selectedDraft);
    if (validation) {
      setError(validation);
      return;
    }
    setIsSaving(true);
    setError("");
    try {
      const updated = await onUpdateEvent(selectedDraft.id, selectedDraft);
      dirty.current = false;
      setSelectedDraft(updated);
      updateUiState(
        { selectedEventId: "", sidebarMode: "idle" },
        { action: "updated-event", event_id: updated.id },
      );
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : "Event could not be saved.",
      );
      if (
        submitError instanceof CalendarApiError &&
        submitError.code.includes("revision_conflict")
      ) {
        setRevisionConflict(true);
        const live = await getFullEvent(runtimeAppId, selectedDraft.id).catch(
          () => null,
        );
        if (live) latestEvent.current = live;
      }
    } finally {
      setIsSaving(false);
    }
  }

  async function submitDelete() {
    if (!selectedDraft) {
      return;
    }
    setIsSaving(true);
    setError("");
    try {
      await onDeleteEvent(selectedDraft);
      dirty.current = false;
      updateUiState(
        { selectedEventId: "", sidebarMode: "idle" },
        { action: "deleted-event", event_id: selectedDraft.id },
      );
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : "Event could not be deleted.",
      );
    } finally {
      setIsSaving(false);
    }
  }

  function closeOverlay() {
    if (
      isSaving ||
      (dirty.current && !window.confirm(t("Discard unsaved changes?")))
    )
      return;
    updateUiState(
      { selectedEventId: "", sidebarMode: "idle" },
      { action: "close-panel" },
    );
  }

  if (uiState.sidebarMode !== "create" && uiState.sidebarMode !== "details") {
    return null;
  }

  const panelDraft =
    uiState.sidebarMode === "create" ? newEvent : selectedDraft;

  return (
    <div
      ref={dialogRef}
      className="calendar-event-overlay"
      role="dialog"
      aria-modal="true"
      aria-label={
        uiState.sidebarMode === "create" ? "Create event" : "Event details"
      }
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          closeOverlay();
        }
      }}
    >
      <div className="calendar-event-overlay__panel">
        <EventPanel
          mode={uiState.sidebarMode === "create" ? "create" : "details"}
          draft={panelDraft}
          error={error}
          isSaving={isSaving}
          canSave={
            uiState.sidebarMode === "create" ||
            (detailsAvailable && !loadingDetails)
          }
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
        >
          {revisionConflict && (
            <div className="calendar-notice" role="alert">
              <p>
                {t("Another version is available. Your draft has been kept.")}
              </p>
              <button
                type="button"
                onClick={() => {
                  if (latestEvent.current) {
                    setSelectedDraft((current) =>
                      current
                        ? {
                            ...current,
                            revision: latestEvent.current!.revision,
                          }
                        : current,
                    );
                    setRevisionConflict(false);
                    setError("");
                  }
                }}
              >
                {t("Keep draft and retry with latest revision")}
              </button>
              <button
                type="button"
                onClick={() => {
                  setSelectedDraft(latestEvent.current);
                  dirty.current = false;
                  setRevisionConflict(false);
                  setError("");
                }}
              >
                {t("Reload latest event")}
              </button>
            </div>
          )}
          {conflicts.length > 0 && (
            <div role="status">
              <p>{t("Overlapping events")}</p>
              {conflicts.map((c, i) => (
                <p key={i}>
                  {c.title} · {new Date(c.startTime).toLocaleString()}
                </p>
              ))}
            </div>
          )}
          <FindTime
            appId={runtimeAppId}
            draft={panelDraft}
            onSelect={setPanelDraft}
          />
        </EventPanel>
      </div>
    </div>
  );
}
