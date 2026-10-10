import * as React from "react";
import type { Entry, LiveNotificationFeedProps } from "./notification-types";
import { LEAVE_MS, staticEntry, useReducedMotion } from "./notification-shared";

/** Arrival/replay state; managed feeds keep receipts in their provider projections. */
export function useLiveNotificationFeed({
  items,
  autoplay = false,
  initial = 2,
  interval = 1500,
  loop = false,
  managed = false,
  unreadCount,
  onReadAll,
  onError,
}: LiveNotificationFeedProps) {
  const reduced = useReducedMotion();
  const startCount =
    autoplay && !reduced
      ? Math.min(Math.max(0, Math.round(initial)), items.length)
      : items.length;
  const [entries, setEntries] = React.useState(() =>
    items.slice(0, startCount).map((item) => staticEntry(item.id, 0)),
  );
  const [readIds, setReadIds] = React.useState(
    () => new Set(items.filter((item) => item.read).map((item) => item.id)),
  );
  const [done, setDone] = React.useState<Record<string, string>>({});
  const [announcement, setAnnouncement] = React.useState("");
  const [busy, setBusy] = React.useState<Set<string>>(new Set());
  const busyRef = React.useRef(new Set<string>());
  const cursor = React.useRef(startCount),
    generation = React.useRef(0),
    paused = React.useRef(false);
  const timers = React.useRef(new Set<number>()),
    bellRef = React.useRef<SVGSVGElement>(null);
  const itemsRef = React.useRef(items);
  itemsRef.current = items;
  const initialRef = React.useRef(initial);
  initialRef.current = initial;
  const reducedRef = React.useRef(reduced);
  reducedRef.current = reduced;
  const entriesRef = React.useRef(entries);
  entriesRef.current = entries;
  const itemsKey = JSON.stringify(items.map((item) => item.id));
  const byId = React.useMemo(
    () => new Map(items.map((item) => [item.id, item])),
    [items],
  );
  const showAll = !autoplay || reduced;
  React.useEffect(() => {
    const pending = timers.current;
    return () => pending.forEach(window.clearTimeout);
  }, []);
  const later = React.useCallback((run: () => void, ms: number) => {
    const timer = window.setTimeout(() => {
      timers.current.delete(timer);
      run();
    }, ms);
    timers.current.add(timer);
  }, []);
  const ringBell = React.useCallback(() => {
    if (reducedRef.current) return;
    bellRef.current?.animate?.(
      [
        { transform: "rotate(0deg)" },
        { transform: "rotate(16deg)" },
        { transform: "rotate(-12deg)" },
        { transform: "rotate(7deg)" },
        { transform: "rotate(-3deg)" },
        { transform: "rotate(0deg)" },
      ],
      { duration: 720, easing: "ease-out" },
    );
  }, []);
  const arrive = React.useCallback(
    (id: string) => {
      const item = itemsRef.current.find((candidate) => candidate.id === id);
      if (!item) return;
      generation.current += 1;
      const entry: Entry = {
        id,
        key: `${id}:${generation.current}`,
        play: 1,
        fresh: !reducedRef.current,
        leaving: false,
        arrived: !managed,
        delay: 0,
        leaveDelay: 0,
      };
      setEntries((prev) => [...prev.filter((e) => e.id !== id), entry]);
      setReadIds((prev) => {
        const next = new Set(prev);
        if (item.read) next.add(id);
        else next.delete(id);
        return next;
      });
      setDone((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      setAnnouncement(`${item.app}: ${item.title}`);
      ringBell();
    },
    [ringBell, managed],
  );
  const removeKeys = React.useCallback(
    (keys: string[], after: number) => {
      later(
        () => setEntries((prev) => prev.filter((e) => !keys.includes(e.key))),
        after,
      );
    },
    [later],
  );
  const clearAll = React.useCallback(() => {
    const visible = entriesRef.current.filter((e) => !e.leaving).reverse();
    if (visible.length === 0) return 0;
    const step = reducedRef.current ? 0 : 60,
      order = new Map(visible.map((e, i) => [e.key, i]));
    setEntries((prev) =>
      prev.map((e) =>
        order.has(e.key)
          ? { ...e, leaving: true, leaveDelay: order.get(e.key)! * step }
          : e,
      ),
    );
    const total = reducedRef.current
      ? 0
      : LEAVE_MS + (visible.length - 1) * step;
    removeKeys(
      visible.map((e) => e.key),
      total,
    );
    return total;
  }, [removeKeys]);
  const restart = React.useCallback(() => {
    const list = itemsRef.current,
      count = Math.min(
        Math.max(0, Math.round(initialRef.current)),
        list.length,
      );
    cursor.current = count;
    generation.current += 1;
    setEntries(
      list
        .slice(0, count)
        .map((item, i) =>
          staticEntry(
            item.id,
            generation.current,
            !reducedRef.current,
            (count - 1 - i) * 90,
          ),
        ),
    );
    setReadIds(
      new Set(list.filter((item) => item.read).map((item) => item.id)),
    );
    setDone({});
  }, []);
  React.useEffect(() => {
    if (showAll || itemsRef.current.length === 0) return;
    let timer = 0;
    const step = () => {
      if (paused.current) {
        timer = window.setTimeout(step, 300);
        return;
      }
      const list = itemsRef.current;
      if (cursor.current < list.length) {
        arrive(list[cursor.current++]!.id);
        timer = window.setTimeout(
          step,
          cursor.current < list.length ? interval : interval * 2.2,
        );
        return;
      }
      if (!loop) return;
      const took = clearAll();
      timer = window.setTimeout(() => {
        restart();
        timer = window.setTimeout(step, 950);
      }, took + 200);
    };
    timer = window.setTimeout(step, 450);
    return () => window.clearTimeout(timer);
  }, [showAll, interval, loop, itemsKey, arrive, clearAll, restart]);
  const lastShowAll = React.useRef(showAll),
    lastItemsKey = React.useRef(itemsKey);
  React.useEffect(() => {
    const modeChanged = lastShowAll.current !== showAll,
      itemsChanged = lastItemsKey.current !== itemsKey;
    const previousIds = new Set<string>(JSON.parse(lastItemsKey.current));
    lastShowAll.current = showAll;
    lastItemsKey.current = itemsKey;
    if (!modeChanged && !itemsChanged) return;
    const list = itemsRef.current;
    if (!showAll) {
      restart();
      return;
    }
    if (modeChanged) {
      generation.current += 1;
      setEntries((prev) => {
        const kept = new Map(
          prev.filter((e) => !e.leaving).map((e) => [e.id, e]),
        );
        return list.map(
          (item) =>
            kept.get(item.id) ?? staticEntry(item.id, generation.current),
        );
      });
      cursor.current = list.length;
      return;
    }
    const ids = new Set(list.map((item) => item.id));
    setEntries((prev) => prev.filter((e) => ids.has(e.id)));
    list
      .filter((item) => !previousIds.has(item.id))
      .forEach((item) => arrive(item.id));
    // Refreshes and pages follow the server timestamps, not fetch completion order.
    setEntries((prev) => {
      const kept = new Map(prev.map((e) => [e.id, e]));
      return list.flatMap((item) =>
        kept.has(item.id) ? [kept.get(item.id)!] : [],
      );
    });
  }, [showAll, itemsKey, restart, arrive]);
  const run = async (
    key: string,
    operation: () => void | Promise<void>,
    success?: () => void,
  ) => {
    if (busyRef.current.has(key)) return;
    busyRef.current.add(key);
    setBusy(new Set(busyRef.current));
    try {
      await operation();
      success?.();
    } catch (error) {
      onError?.(error);
    } finally {
      busyRef.current.delete(key);
      setBusy(new Set(busyRef.current));
    }
  };
  const markRead = (id: string) => {
    if (!managed)
      setReadIds((prev) => (prev.has(id) ? prev : new Set(prev).add(id)));
  };
  const live = entries.filter((e) => !e.leaving);
  const unread =
    unreadCount ??
    live.filter((e) => (managed ? !byId.get(e.id)?.read : !readIds.has(e.id)))
      .length;
  const canRead =
    live.some((e) => byId.get(e.id)?.readable !== false) &&
    (!managed || Boolean(onReadAll));
  return {
    readIds,
    done,
    announcement,
    entries,
    byId,
    reduced,
    bellRef,
    busy,
    paused,
    live,
    unread,
    canRead,
    run,
    markRead,
    setEntries,
    setReadIds,
    setDone,
    clearAll,
    removeKeys,
  };
}
