import {
  observeMaverickVisibility,
  maverickAppIsVisible,
} from "@maverick/pwa-cache";
import { useEffect, useRef, useState } from "react";
import { findFreeTime, checkAvailability } from "@/api";
import {
  readPreferences,
  t,
  formatCalendarDate,
  formatCalendarTime,
} from "@/preferences";
import type { DraftEvent } from "./calendar-types";
export function FindTime({
  appId,
  draft,
  onSelect,
}: {
  appId: string;
  draft: DraftEvent | null;
  onSelect: (patch: DraftEvent) => void;
}) {
  const [slots, setSlots] = useState<
      Array<{ startTime: string; endTime: string }>
    >([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [conflicts, setConflicts] = useState<
    Array<{ title: string; startTime: string }>
  >([]);
  const read = useRef<AbortController | null>(null);
  useEffect(() => {
    const stop = observeMaverickVisibility((visible) => {
      if (!visible) {
        read.current?.abort();
        setBusy(false);
      }
    });
    return () => {
      stop();
      read.current?.abort();
    };
  }, [appId]);
  async function find() {
    if (!draft?.startTime || !draft?.endTime || !maverickAppIsVisible()) return;
    read.current?.abort();
    const controller = new AbortController();
    read.current = controller;
    setBusy(true);
    setError("");
    try {
      const start = new Date(draft.startTime),
        end = new Date(start);
      end.setDate(end.getDate() + 14);
      const prefs = readPreferences();
      const [availability, result] = await Promise.all([
        checkAvailability(
          appId,
          {
            startTime: draft.startTime.toISOString(),
            endTime: draft.endTime.toISOString(),
            ignore_event_id: draft.id,
            attendees: draft.attendees,
          },
          controller.signal,
        ),
        findFreeTime(
          appId,
          {
            start_after: start.toISOString(),
            end_before: end.toISOString(),
            duration_minutes: Math.max(
              1,
              Math.ceil((draft.endTime.getTime() - start.getTime()) / 60000),
            ),
            timezone:
              draft.timezone ||
              Intl.DateTimeFormat().resolvedOptions().timeZone,
            work_start: prefs.workStart,
            work_end: prefs.workEnd,
            work_days: prefs.workDays,
            buffer_minutes: prefs.bufferMinutes,
            ignore_event_id: draft.id,
            attendees: draft.attendees,
            limit: 5,
          },
          controller.signal,
        ),
      ]);
      if (controller.signal.aborted) return;
      setConflicts(availability.conflicts || []);
      setSlots(result.slots || []);
    } catch (err) {
      if (!controller.signal.aborted)
        setError(err instanceof Error ? err.message : "Availability failed");
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return (
    <details>
      <summary>{t("Find a time")}</summary>
      <div>
        <p>
          {t("Known local events only; invitee calendars may be incomplete.")}
        </p>
        <button
          type="button"
          disabled={
            busy ||
            !draft?.startTime ||
            !Number.isFinite(draft.startTime.getTime())
          }
          onClick={() => void find()}
        >
          {busy ? "…" : t("Find a time")}
        </button>
        {error && <p role="alert">{error}</p>}
        {conflicts.map((c, i) => (
          <p key={i}>
            {t("Overlapping events")}: {c.title}
          </p>
        ))}
        {slots.map((slot) => (
          <button
            type="button"
            key={slot.startTime}
            onClick={() =>
              onSelect({
                startTime: new Date(slot.startTime),
                endTime: new Date(slot.endTime),
              })
            }
          >
            {t("Use this time")} ·{" "}
            {formatCalendarDate(new Date(slot.startTime), {
              dateStyle: "short",
            })}{" "}
            {formatCalendarTime(new Date(slot.startTime))}
          </button>
        ))}
        {!busy && !error && !slots.length && (
          <p>{t("No times proposed yet")}</p>
        )}
      </div>
    </details>
  );
}
