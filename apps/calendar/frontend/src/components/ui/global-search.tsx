import {
  observeMaverickVisibility,
  maverickAppIsVisible,
} from "@maverick/pwa-cache";
import { eventDisplayDate } from "./calendar-utils";
import { useEffect, useRef, useState } from "react";
import { searchEvents } from "@/api";
import { t, formatCalendarDate, formatCalendarTime } from "@/preferences";
import type { Event } from "./calendar-types";
export function GlobalSearch({
  appId,
  query,
  onSelect,
}: {
  appId: string;
  query: string;
  onSelect: (event: Event) => void;
}) {
  const [rows, setRows] = useState<Event[]>([]),
    [hasMore, setHasMore] = useState(false),
    [error, setError] = useState("");
  const [from, setFrom] = useState(""),
    [to, setTo] = useState(""),
    [loading, setLoading] = useState(false);
  const read = useRef<AbortController | null>(null);
  async function search(offset: number) {
    if (!maverickAppIsVisible()) return;
    read.current?.abort();
    const controller = new AbortController();
    read.current = controller;
    setLoading(true);
    setError("");
    try {
      if (from && to && from >= to)
        throw new Error(t("End Time") + " > " + t("Start Time"));
      const result = await searchEvents(
        appId,
        query,
        offset,
        {
          ...(from
            ? { start_after: new Date(`${from}T00:00`).toISOString() }
            : {}),
          ...(to ? { end_before: new Date(`${to}T00:00`).toISOString() } : {}),
        },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setRows((current) =>
        offset ? [...current, ...result.events] : result.events,
      );
      setHasMore(result.hasMore);
    } catch (err) {
      if (!controller.signal.aborted)
        setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }
  useEffect(() => {
    setRows([]);
    let timer: number | undefined;
    const stop = observeMaverickVisibility((visible) => {
      window.clearTimeout(timer);
      read.current?.abort();
      setLoading(false);
      if (visible) timer = window.setTimeout(() => void search(0), 250);
    });
    return () => {
      stop();
      window.clearTimeout(timer);
      read.current?.abort();
    };
  }, [appId, query, from, to]);
  return (
    <section
      className="calendar-search-results"
      aria-label={t("Search all calendars")}
    >
      <p>{t("Search all calendars")}</p>
      <div className="calendar-search-range">
        <label>
          {t("From")}
          <input
            type="date"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
          />
        </label>
        <label>
          {t("To")}
          <input
            type="date"
            value={to}
            onChange={(e) => setTo(e.target.value)}
          />
        </label>
      </div>
      {error && <p role="alert">{error}</p>}
      {rows.map((event) => (
        <button type="button" key={event.id} onClick={() => onSelect(event)}>
          <strong>{event.title}</strong>
          <span>
            {formatCalendarDate(eventDisplayDate(event), {
              dateStyle: "medium",
            })}{" "}
            ·{" "}
            {event.all_day ? t("All day") : formatCalendarTime(event.startTime)}
          </span>
        </button>
      ))}
      {!loading && !rows.length && <p>{t("No events found")}</p>}
      {loading && <p role="status">…</p>}
      {hasMore && (
        <button
          type="button"
          disabled={loading}
          onClick={() => void search(rows.length)}
        >
          {t("Load more")}
        </button>
      )}
    </section>
  );
}
