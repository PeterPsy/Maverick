import * as React from "react";
import { Check, X } from "lucide-react";
import type {
  Entry,
  LiveNotification,
  NotificationAction,
} from "./notification-types";
import { AppTile, cx, ENTER_MS, LEAVE_MS, TINT } from "./notification-shared";
import { MessageDetail, DeliveryDetail } from "./notification-message-route";
import { RideDetail } from "./notification-ride";
import { CalendarDetail, PaymentDetail } from "./notification-payment-calendar";
import { CodeDetail } from "./notification-code";
import { FlightDetail, FitnessDetail } from "./notification-flight-fitness";
function Detail({
  item,
  ...story
}: {
  item: LiveNotification;
  play: number;
  delay: number;
  reduced: boolean;
}) {
  switch (item.kind) {
    case "generic":
      return null;
    case "message":
      return <MessageDetail item={item} {...story} />;
    case "delivery":
      return <DeliveryDetail item={item} {...story} />;
    case "ride":
      return <RideDetail item={item} {...story} />;
    case "payment":
      return <PaymentDetail item={item} {...story} />;
    case "calendar":
      return <CalendarDetail item={item} {...story} />;
    case "code":
      return <CodeDetail item={item} {...story} />;
    case "flight":
      return <FlightDetail item={item} {...story} />;
    case "fitness":
      return <FitnessDetail item={item} {...story} />;
  }
}
export function NotificationCard({
  item,
  entry,
  read,
  done,
  reduced,
  onOpen,
  onAction,
  onDismiss,
}: {
  item: LiveNotification;
  entry: Entry;
  read: boolean;
  done?: string;
  reduced: boolean;
  onOpen: () => void;
  onAction: (action: NotificationAction) => void;
  onDismiss: () => void;
}) {
  const [entered, setEntered] = React.useState(!entry.fresh || reduced);
  React.useEffect(() => {
    if (entered) return;
    if (reduced) {
      setEntered(true);
      return;
    }
    let second = 0;
    const first = window.requestAnimationFrame(() => {
      second = window.requestAnimationFrame(() => setEntered(true));
    });
    return () => {
      window.cancelAnimationFrame(first);
      window.cancelAnimationFrame(second);
    };
  }, [entered, reduced]);
  const shown = entered && !entry.leaving,
    duration = entry.leaving ? LEAVE_MS : ENTER_MS;
  const lag = entry.leaving ? entry.leaveDelay : entry.delay;
  const ease = entry.leaving
    ? "cubic-bezier(0.4, 0, 0.2, 1)"
    : "cubic-bezier(0.2, 0.9, 0.25, 1.12)";
  const storyDelay = entry.fresh ? 260 + entry.delay : 0;
  return (
    <div
      role="listitem"
      data-notification={item.id}
      data-kind={item.kind}
      data-read={read ? "" : undefined}
      data-leaving={entry.leaving ? "" : undefined}
      data-play={entry.play}
      className="grid"
      style={{
        gridTemplateRows: shown ? "1fr" : "0fr",
        transition: reduced
          ? "none"
          : `grid-template-rows ${duration}ms ${ease} ${lag}ms`,
      }}
    >
      <div className="min-h-0 overflow-hidden">
        <div className="px-1 pb-2 pt-0.5">
          <article
            aria-label={`${item.app}: ${item.title}`}
            aria-busy={item.pending}
            className="group relative rounded-2xl border border-border bg-card p-3 text-card-foreground shadow-sm"
            style={{
              transform: shown
                ? "none"
                : entry.leaving
                  ? "translateX(18%) scale(0.98)"
                  : "translateY(-16px) scale(0.96)",
              opacity: shown ? 1 : 0,
              transition: reduced
                ? "none"
                : `transform ${duration}ms ${ease} ${lag}ms, opacity ${Math.round(duration * 0.7)}ms ease ${lag}ms`,
            }}
          >
            <div className="flex gap-3">
              <AppTile
                kind={item.kind}
                accent={item.accent}
                icon={item.icon}
                play={entry.play}
                delay={storyDelay}
                reduced={reduced}
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5 pr-6 text-xs text-muted-foreground">
                  <span className="truncate font-medium">{item.app}</span>
                  {(entry.arrived || item.time) && (
                    <>
                      <span aria-hidden>·</span>
                      <span data-time className="min-w-0 tabular-nums">
                        {entry.arrived ? "ora" : item.time}
                      </span>
                    </>
                  )}
                </div>
                <button
                  type="button"
                  data-open
                  disabled={item.pending}
                  onClick={onOpen}
                  onKeyDown={(event) => {
                    if (event.key !== "Delete" && event.key !== "Backspace")
                      return;
                    event.preventDefault();
                    onDismiss();
                  }}
                  className="mt-0.5 block w-full text-left text-sm font-semibold leading-snug outline-none after:absolute after:inset-0 after:rounded-2xl after:content-[''] focus-visible:after:ring-2 focus-visible:after:ring-ring disabled:opacity-50"
                >
                  {item.title}
                </button>
                {item.body && (
                  <p className="mt-0.5 text-[13px] leading-snug text-muted-foreground">
                    {item.body}
                  </p>
                )}
                <div
                  className={cx(
                    item.kind !== "generic" && "mt-2.5",
                    !item.accent && "text-primary",
                  )}
                  style={{ color: item.accent }}
                >
                  <Detail
                    item={item}
                    play={entry.play}
                    delay={storyDelay}
                    reduced={reduced}
                  />
                  {done ? (
                    <div className="relative z-[1] mt-2.5">
                      <span
                        data-done
                        className="inline-flex h-7 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium"
                        style={{ background: TINT }}
                      >
                        <Check aria-hidden className="size-3.5" />
                        <span className="text-foreground">{done}</span>
                      </span>
                    </div>
                  ) : (
                    item.actions &&
                    item.actions.length > 0 && (
                      <div className="relative z-[1] mt-2.5 flex flex-wrap items-center gap-2">
                        {item.actions.map((action, i) => (
                          <button
                            key={action.id ?? action.label}
                            type="button"
                            data-action={action.label}
                            disabled={item.pending}
                            onClick={(event) => {
                              event.stopPropagation();
                              onAction(action);
                            }}
                            className={cx(
                              "h-7 rounded-full px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
                              i === 0
                                ? "bg-foreground text-background hover:bg-foreground/85"
                                : "border border-border bg-background text-foreground hover:bg-muted",
                            )}
                          >
                            {action.label}
                          </button>
                        ))}
                      </div>
                    )
                  )}
                </div>
              </div>
            </div>
            {!read && (
              <span
                data-unread
                aria-hidden
                className={cx(
                  "absolute right-3.5 top-3.5 size-2 rounded-full transition-opacity group-hover:opacity-0",
                  !item.accent && "bg-primary",
                )}
                style={item.accent ? { background: item.accent } : undefined}
              />
            )}
            <button
              type="button"
              data-dismiss
              disabled={item.pending}
              aria-label={`Chiudi notifica: ${item.title}`}
              onClick={(event) => {
                event.stopPropagation();
                onDismiss();
              }}
              className="absolute right-2 top-2 z-[2] grid size-6 place-items-center rounded-full text-muted-foreground opacity-0 transition-opacity hover:bg-muted hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring group-hover:opacity-100 disabled:opacity-40"
            >
              <X aria-hidden className="size-3.5" />
            </button>
          </article>
        </div>
      </div>
    </div>
  );
}
