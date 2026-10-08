import { useEffect, useRef, useState } from "react";
import { t } from "./preferences";
import type { CalendarEvent } from "./types";
export function usePendingDeletion(
  commit: (event: CalendarEvent) => Promise<void>,
) {
  const [pending, setPending] = useState<CalendarEvent[]>([]);
  const timers = useRef(new Map<string, number>());
  const latest = useRef(commit);
  latest.current = commit;
  useEffect(
    () => () => {
      for (const timer of timers.current.values()) window.clearTimeout(timer);
    },
    [],
  );
  function undo(id: string) {
    window.clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setPending((current) => current.filter((e) => e.id !== id));
  }
  function schedule(event: CalendarEvent) {
    if (timers.current.has(event.id)) return;
    setPending((current) => [...current, event]);
    timers.current.set(
      event.id,
      window.setTimeout(() => {
        timers.current.delete(event.id);
        void latest
          .current(event)
          .catch(() => {})
          .finally(() =>
            setPending((current) => current.filter((e) => e.id !== event.id)),
          );
      }, 8000),
    );
  }
  const notice = (
    <>
      {pending.map((event) => (
        <div className="calendar-notice" role="status" key={event.id}>
          {t("Event deleted")}: {event.title}
          <button type="button" onClick={() => undo(event.id)}>
            {t("Undo")}
          </button>
        </div>
      ))}
    </>
  );
  return { pendingIds: new Set(pending.map((e) => e.id)), schedule, notice };
}
