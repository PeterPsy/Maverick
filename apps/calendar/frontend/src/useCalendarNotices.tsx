import { useEffect, useState } from "react";
import { t, formatCalendarTime } from "./preferences";

/** Conflict warnings belong to the editor; durable reminders belong to the shell inbox. */
export function useCalendarNotices() {
  const [conflicts, setConflicts] = useState<
    Array<{ id: string; title: string; startTime: string }>
  >([]);
  useEffect(() => {
    const warnings = (event: globalThis.Event) =>
      setConflicts((event as CustomEvent).detail);
    window.addEventListener("calendar-conflicts", warnings);
    return () => window.removeEventListener("calendar-conflicts", warnings);
  }, []);
  return (
    !!conflicts.length && (
      <div role="status" className="calendar-notice">
        {t("Overlapping events")}:{" "}
        {conflicts
          .map(
            (c) => `${c.title} (${formatCalendarTime(new Date(c.startTime))})`,
          )
          .join(", ")}
        <button type="button" onClick={() => setConflicts([])}>
          {t("Close")}
        </button>
      </div>
    )
  );
}
