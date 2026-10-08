import { useEffect, useRef, useState } from "react";
import {
  maverickAppIsVisible,
  observeMaverickVisibility,
} from "@maverick/pwa-cache";
import { t, formatCalendarTime } from "./preferences";
import type { CalendarEvent } from "./types";
export function useCalendarNotices(events: CalendarEvent[]) {
  const latest = useRef(events);
  latest.current = events;
  const fired = useRef(new Set<string>());
  const [reminders, setReminders] = useState<CalendarEvent[]>([]);
  const [conflicts, setConflicts] = useState<
    Array<{ id: string; title: string; startTime: string }>
  >([]);
  useEffect(() => {
    let timer: number | undefined;
    const tick = () => {
      if (!maverickAppIsVisible({ requireOnline: false })) return;
      const now = Date.now();
      for (const event of latest.current) {
        if (event.source === "google_calendar" || event.status === "cancelled")
          continue;
        for (const reminder of event.reminders || []) {
          const minutes = (reminder as { minutes_before?: number })
            .minutes_before;
          if (typeof minutes !== "number") continue;
          const due = event.startTime.getTime() - minutes * 60000;
          const key = `${event.id}:${due}`;
          if (due <= now && due > now - 60000 && !fired.current.has(key)) {
            fired.current.add(key);
            setReminders((current) => [
              ...current.filter((e) => e.id !== event.id),
              event,
            ]);
          }
        }
      }
    };
    const stop = observeMaverickVisibility(
      (visible) => {
        window.clearInterval(timer);
        if (visible) {
          tick();
          timer = window.setInterval(tick, 15000);
        }
      },
      { requireOnline: false },
    );
    const warnings = (event: globalThis.Event) =>
      setConflicts((event as CustomEvent).detail);
    window.addEventListener("calendar-conflicts", warnings);
    return () => {
      stop();
      window.clearInterval(timer);
      window.removeEventListener("calendar-conflicts", warnings);
    };
  }, []);
  const notices = (
    <>
      {reminders.map((event) => (
        <div role="status" className="calendar-notice" key={event.id}>
          {t("Reminder")}: {event.title} · {formatCalendarTime(event.startTime)}
          <button
            type="button"
            onClick={() =>
              setReminders((current) =>
                current.filter((e) => e.id !== event.id),
              )
            }
          >
            {t("Close")}
          </button>
        </div>
      ))}
      {!!conflicts.length && (
        <div role="status" className="calendar-notice">
          {t("Overlapping events")}:{" "}
          {conflicts
            .map(
              (c) =>
                `${c.title} (${formatCalendarTime(new Date(c.startTime))})`,
            )
            .join(", ")}
          <button type="button" onClick={() => setConflicts([])}>
            {t("Close")}
          </button>
        </div>
      )}
    </>
  );
  return notices;
}
