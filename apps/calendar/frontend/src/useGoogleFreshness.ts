import { useEffect, useRef, useState } from "react";
import {
  maverickAppIsVisible,
  observeMaverickVisibility,
} from "@maverick/pwa-cache";
import { syncCalendar } from "./api";
import type { CalendarConnection, CalendarRemoteCalendar } from "./types";
import { calendarWindow } from "./pwaCache";
import { t } from "./preferences";
export function useGoogleFreshness(
  appId: string,
  connections: CalendarConnection[],
  calendars: CalendarRemoteCalendar[],
  date: Date,
  refresh: () => Promise<void>,
) {
  const [status, setStatus] = useState(""),
    [running, setRunning] = useState(false);
  const generation = useRef(0);
  const attempts = useRef(
      new Map<string, { next: number; failures: number }>(),
    ),
    inFlight = useRef(false);
  const latest = useRef({ connections, calendars, date, refresh });
  latest.current = { connections, calendars, date, refresh };
  const runRef = useRef<(force?: boolean) => Promise<void>>(async () => {});
  async function run(force = false) {
    if (
      !maverickAppIsVisible() ||
      navigator.onLine === false ||
      inFlight.current
    )
      return;
    const currentGeneration = generation.current;
    inFlight.current = true;
    setRunning(true);
    let changed = false,
      failure = "";
    try {
      for (const connection of latest.current.connections.filter(
        (c) => c.status === "connected",
      )) {
        if (
          generation.current !== currentGeneration ||
          !maverickAppIsVisible() ||
          !online()
        )
          break;
        const last = Date.parse(connection.last_sync_at || "") || 0;
        const backoff = attempts.current.get(connection.id) || {
          next: 0,
          failures: 0,
        };
        const window = calendarWindow(latest.current.date);
        const enabled = latest.current.calendars.filter(
          (c) => c.connection_id === connection.id && c.sync_enabled !== false,
        );
        const uncovered = enabled.some(
          (c) =>
            c.sync_status?.time_min &&
            (c.sync_status.time_min > window.start_after ||
              (c.sync_status.time_max || "") < window.end_before),
        );
        const partial = enabled.some(
          (c) => c.sync_status?.status === "partial" || c.sync_status?.has_more,
        );
        if (
          !force &&
          ((Date.now() < backoff.next &&
            (backoff.failures > 0 || !uncovered)) ||
            (!uncovered && !partial && Date.now() - last < 900000))
        )
          continue;
        try {
          const result = await syncCalendar(
            appId,
            connection.id,
            uncovered
              ? {
                  syncMode: "bounded",
                  timeMin: window.start_after,
                  timeMax: window.end_before,
                }
              : {},
          );
          if (generation.current !== currentGeneration) return;
          changed = true;
          attempts.current.set(connection.id, {
            next: Date.now() + (result.synced ? 900000 : 60000),
            failures: 0,
          });
          if (!result.synced)
            failure = t(
              "Sync is partial; continue syncing to fetch remaining pages.",
            );
        } catch (err) {
          if (generation.current !== currentGeneration) return;
          const failures = backoff.failures + 1;
          attempts.current.set(connection.id, {
            next: Date.now() + Math.min(900000, 30000 * 2 ** failures),
            failures,
          });
          failure = err instanceof Error ? err.message : "Sync failed";
        }
      }
      if (changed && generation.current === currentGeneration)
        await latest.current.refresh();
      if (generation.current === currentGeneration) setStatus(failure);
    } finally {
      if (generation.current === currentGeneration) {
        inFlight.current = false;
        setRunning(false);
      }
    }
  }
  runRef.current = run;
  useEffect(() => {
    generation.current += 1;
    attempts.current.clear();
    inFlight.current = false;
    setStatus("");
    setRunning(false);
    let timer: number | undefined;
    const stop = observeMaverickVisibility((visible) => {
      window.clearInterval(timer);
      if (visible) {
        void runRef.current();
        timer = window.setInterval(() => void runRef.current(), 60000);
      }
    });
    return () => {
      generation.current += 1;
      stop();
      window.clearInterval(timer);
    };
  }, [appId]);
  useEffect(() => {
    void runRef.current();
  }, [connections, date.getMonth(), date.getFullYear()]);
  return { status, running, syncNow: () => runRef.current(true) };
}

function online() {
  return navigator.onLine !== false;
}
