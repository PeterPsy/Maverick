"use client";

import { Bell, Check } from "lucide-react";
import type {
  LiveNotificationFeedProps,
  NotificationAction,
} from "./notification-types";
import { cx, DEFAULT_HEIGHT, LEAVE_MS } from "./notification-shared";
import { useLiveNotificationFeed } from "./use-live-notification-feed";
import { NotificationCard } from "./notification-card";
export type * from "./notification-types";

/** The supplied live feed, with provider-controlled receipts for real app inboxes. */
export function LiveNotificationFeed({
  items,
  title = "Notifiche",
  autoplay = false,
  initial = 2,
  interval = 1500,
  loop = false,
  height = DEFAULT_HEIGHT,
  managed = false,
  unreadCount,
  onOpen,
  onReadAll,
  onClear,
  onAction,
  onDismiss,
  onError,
  ref,
  className,
  onPointerEnter,
  onPointerLeave,
  onFocus,
  onBlur,
  ...rest
}: LiveNotificationFeedProps) {
  const {
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
  } = useLiveNotificationFeed({
    items,
    autoplay,
    initial,
    interval,
    loop,
    managed,
    unreadCount,
    onReadAll,
    onError,
  });
  return (
    <div
      ref={ref}
      data-slot="live-notification-feed"
      data-unread={unread}
      className={cx(
        "w-full rounded-[28px] border border-border bg-muted/60 p-2 text-foreground shadow-sm backdrop-blur-xl",
        className,
      )}
      onPointerEnter={(event) => {
        paused.current = true;
        onPointerEnter?.(event);
      }}
      onPointerLeave={(event) => {
        paused.current = event.currentTarget.contains(document.activeElement);
        onPointerLeave?.(event);
      }}
      onFocus={(event) => {
        paused.current = true;
        onFocus?.(event);
      }}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null))
          paused.current = event.currentTarget.matches(":hover");
        onBlur?.(event);
      }}
      {...rest}
    >
      <div className="flex flex-wrap items-center gap-2 px-3 pb-2.5 pt-2">
        <Bell
          ref={bellRef}
          aria-hidden
          className="size-[18px]"
          style={{ transformOrigin: "50% 12%" }}
          strokeWidth={1.8}
        />
        <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
        <span
          data-count
          aria-label={`${unread} da leggere`}
          className={cx(
            "min-w-5 rounded-full bg-foreground px-1.5 text-center text-[11px] font-semibold leading-5 text-background tabular-nums transition-opacity",
            unread === 0 && "opacity-0",
          )}
        >
          {unread}
        </span>
        <div className="ml-auto flex items-center gap-0.5">
          {canRead && (
            <button
              type="button"
              data-read-all
              disabled={
                unread === 0 ||
                busy.has("read-all") ||
                items.some((item) => item.pending)
              }
              onClick={() =>
                void run(
                  "read-all",
                  () => onReadAll?.(),
                  () => {
                    if (!managed)
                      setReadIds(
                        (prev) => new Set([...prev, ...live.map((e) => e.id)]),
                      );
                  },
                )
              }
              className="rounded-full px-2.5 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-background hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40"
            >
              Segna lette
            </button>
          )}
          <button
            type="button"
            data-clear
            disabled={
              live.length === 0 ||
              busy.has("clear") ||
              items.some((item) => item.pending)
            }
            onClick={() =>
              void run(
                "clear",
                () => onClear?.(),
                () => {
                  if (!managed) clearAll();
                },
              )
            }
            className="rounded-full px-2.5 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-background hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40"
          >
            {managed ? "Chiudi visibili" : "Svuota"}
          </button>
        </div>
      </div>
      <div className="relative">
        <div
          role="list"
          aria-label={title}
          className="overflow-y-auto overscroll-contain px-0.5 pb-6 [scrollbar-width:thin]"
          style={{
            height,
            maskImage:
              "linear-gradient(to bottom, black calc(100% - 28px), transparent)",
            WebkitMaskImage:
              "linear-gradient(to bottom, black calc(100% - 28px), transparent)",
          }}
        >
          {[...entries].reverse().map((entry) => {
            const item = byId.get(entry.id);
            if (!item) return null;
            const pending =
              item.pending ||
              busy.has(entry.id) ||
              busy.has("clear") ||
              busy.has("read-all");
            return (
              <NotificationCard
                key={entry.key}
                item={{ ...item, pending }}
                entry={entry}
                read={managed ? Boolean(item.read) : readIds.has(entry.id)}
                done={item.done ?? done[entry.id]}
                reduced={reduced}
                onOpen={() => {
                  markRead(entry.id);
                  if (!managed)
                    setEntries((prev) =>
                      prev.map((e) =>
                        e.key === entry.key
                          ? { ...e, play: e.play + 1, fresh: false, delay: 0 }
                          : e,
                      ),
                    );
                  onOpen?.(entry.id);
                }}
                onAction={(action: NotificationAction) =>
                  void run(
                    entry.id,
                    () => onAction?.(entry.id, action.label, action.id),
                    () => {
                      markRead(entry.id);
                      if (!managed)
                        setDone((prev) => ({
                          ...prev,
                          [entry.id]: action.done ?? action.label,
                        }));
                    },
                  )
                }
                onDismiss={() => {
                  if (pending) return;
                  void run(
                    entry.id,
                    () => onDismiss?.(entry.id),
                    () => {
                      if (managed) return;
                      setEntries((prev) =>
                        prev.map((e) =>
                          e.key === entry.key
                            ? { ...e, leaving: true, leaveDelay: 0 }
                            : e,
                        ),
                      );
                      removeKeys([entry.key], reduced ? 0 : LEAVE_MS);
                    },
                  );
                }}
              />
            );
          })}
        </div>
        {entries.length === 0 && (
          <div
            data-empty
            className="pointer-events-none absolute inset-0 grid place-items-center text-center"
          >
            <div>
              <span className="mx-auto grid size-10 place-items-center rounded-full bg-background text-muted-foreground">
                <Check aria-hidden className="size-5" />
              </span>
              <p className="mt-2 text-sm font-medium">Nessuna notifica</p>
              <p className="text-xs text-muted-foreground">
                Le nuove notifiche appariranno qui.
              </p>
            </div>
          </div>
        )}
      </div>
      <p aria-live="polite" className="sr-only">
        {announcement}
      </p>
    </div>
  );
}
export default LiveNotificationFeed;
