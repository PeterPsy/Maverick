import * as React from "react";
import { Check } from "lucide-react";
import type {
  PaymentNotification,
  CalendarNotification,
  StoryProps,
} from "./notification-types";
import { initialsOf } from "./notification-shared";

const REEL = Array.from({ length: 20 }, (_, i) => i % 10);
export function PaymentDetail({
  item,
  play,
  delay,
  reduced,
}: StoryProps & { item: PaymentNotification }) {
  const animate = play > 0 && !reduced;
  const formatted = React.useMemo(() => {
    try {
      return new Intl.NumberFormat(item.locale ?? "it-IT", {
        style: "currency",
        currency: item.currency ?? "EUR",
      }).format(Math.abs(item.amount));
    } catch {
      return String(Math.abs(item.amount));
    }
  }, [item.amount, item.currency, item.locale]);
  const text = `${item.amount < 0 ? "−" : "+"}${formatted}`;
  const [rolled, setRolled] = React.useState(!animate);
  const badgeRef = React.useRef<HTMLSpanElement>(null);
  const chars = Array.from(text),
    digitCount = chars.filter((ch) => /\d/.test(ch)).length;
  const rollMs = (order: number) => 900 + order * 110;
  React.useEffect(() => {
    if (!animate) {
      setRolled(true);
      return;
    }
    setRolled(false);
    const start = Math.max(80, delay);
    const timer = window.setTimeout(() => setRolled(true), start);
    const pop = badgeRef.current?.animate?.(
      [
        { transform: "scale(0)", opacity: 0 },
        { transform: "scale(1.25)", opacity: 1, offset: 0.6 },
        { transform: "scale(1)", opacity: 1 },
      ],
      {
        duration: 380,
        delay: start + rollMs(Math.max(0, digitCount - 1)),
        easing: "ease-out",
        fill: "backwards",
      },
    );
    return () => {
      window.clearTimeout(timer);
      pop?.cancel();
    };
  }, [play, animate, delay, digitCount]);
  let order = 0;
  return (
    <div
      data-detail="payment"
      data-amount={text}
      className="flex items-center gap-2"
    >
      <span className="sr-only">{text}</span>
      <span
        aria-hidden
        className="flex items-baseline text-2xl font-semibold leading-none tracking-tight text-foreground tabular-nums"
      >
        {chars.map((ch, i) => {
          if (!/\d/.test(ch)) return <span key={i}>{ch}</span>;
          const digit = Number(ch),
            index = order++;
          return (
            <span
              key={i}
              className="relative inline-block h-[1.15em] overflow-hidden leading-[1.15]"
            >
              <span className="invisible">0</span>
              <span
                data-reel={digit}
                className="absolute inset-x-0 top-0 flex flex-col"
                style={{
                  transform: `translateY(-${(rolled ? 10 + digit : 0) * 1.15}em)`,
                  transition:
                    rolled && animate
                      ? `transform ${rollMs(index)}ms cubic-bezier(0.15, 0.85, 0.25, 1)`
                      : "none",
                }}
              >
                {REEL.map((n, k) => (
                  <span key={k}>{n}</span>
                ))}
              </span>
            </span>
          );
        })}
      </span>
      <span
        ref={badgeRef}
        aria-hidden
        className="grid size-5 place-items-center rounded-full"
        style={{ background: "currentColor" }}
      >
        <Check className="size-3 text-white" />
      </span>
    </div>
  );
}
function DateSheet({ day, locale }: { day: Date; locale: string }) {
  return (
    <div
      className="absolute inset-0 overflow-hidden rounded-lg border border-border bg-card shadow-sm"
      style={{ transformOrigin: "50% 0%", backfaceVisibility: "hidden" }}
    >
      <div style={{ background: "currentColor" }}>
        <span className="block text-center text-[9px] font-semibold uppercase leading-[15px] tracking-wide text-white">
          {day.toLocaleDateString(locale, { month: "short" })}
        </span>
      </div>
      <div className="flex flex-col items-center pt-1">
        <span className="text-lg font-semibold leading-none text-foreground tabular-nums">
          {day.getDate()}
        </span>
        <span className="mt-0.5 text-[9px] uppercase leading-none text-muted-foreground">
          {day.toLocaleDateString(locale, { weekday: "short" })}
        </span>
      </div>
    </div>
  );
}
export function CalendarDetail({
  item,
  play,
  delay,
  reduced,
}: StoryProps & { item: CalendarNotification }) {
  const animate = play > 0 && !reduced,
    locale = item.locale ?? "it-IT";
  const event = React.useMemo(() => {
    const [year, month, day] = item.date.split("-").map(Number);
    return new Date(year, month - 1, day);
  }, [item.date]);
  const torn = React.useMemo(
    () =>
      [1, 2, 3, 4].map(
        (back) =>
          new Date(
            event.getFullYear(),
            event.getMonth(),
            event.getDate() - back,
          ),
      ),
    [event],
  );
  const sheetsRef = React.useRef<HTMLDivElement>(null),
    peopleRef = React.useRef<HTMLDivElement>(null);
  const people = item.attendees ?? [];
  React.useEffect(() => {
    if (!animate) return;
    const start = Math.max(80, delay),
      sheets = Array.from(sheetsRef.current?.children ?? []);
    const tears = sheets.map((sheet, i) =>
      sheet.animate?.(
        [
          { transform: "rotateX(0deg) translateY(0)", opacity: 1 },
          {
            transform: "rotateX(-70deg) translateY(-3px)",
            opacity: 1,
            offset: 0.55,
          },
          { transform: "rotateX(-110deg) translateY(-12px)", opacity: 0 },
        ],
        {
          duration: 300,
          delay: start + (sheets.length - 1 - i) * 150,
          easing: "cubic-bezier(0.4, 0, 0.6, 1)",
          fill: "both",
        },
      ),
    );
    const pops = Array.from(peopleRef.current?.children ?? []).map(
      (person, i) =>
        person.animate?.(
          [
            { transform: "scale(0)", opacity: 0 },
            { transform: "scale(1.15)", opacity: 1, offset: 0.6 },
            { transform: "scale(1)", opacity: 1 },
          ],
          {
            duration: 320,
            delay: start + sheets.length * 150 + 120 + i * 90,
            easing: "ease-out",
            fill: "backwards",
          },
        ),
    );
    return () =>
      [...tears, ...pops].forEach((animation) => animation?.cancel());
  }, [play, animate, delay]);
  return (
    <div data-detail="calendar" className="flex items-center gap-3">
      <div
        className="relative h-14 w-12 shrink-0 [perspective:420px]"
        aria-label={item.date}
      >
        <DateSheet day={event} locale={locale} />
        {animate && (
          <div
            ref={sheetsRef}
            data-sheets
            className="absolute inset-0"
            aria-hidden
          >
            {torn.map((day) => (
              <DateSheet key={day.getTime()} day={day} locale={locale} />
            ))}
          </div>
        )}
      </div>
      {people.length > 0 && (
        <div className="flex items-center">
          <div ref={peopleRef} className="flex -space-x-1.5">
            {people.slice(0, 3).map((name, i) => (
              <span
                key={`${name}-${i}`}
                title={name}
                className="grid size-6 place-items-center rounded-full border-2 border-card bg-muted text-[9px] font-semibold text-foreground"
              >
                {initialsOf(name)}
              </span>
            ))}
          </div>
          {people.length > 3 && (
            <span className="ml-1.5 text-[11px] text-muted-foreground">
              +{people.length - 3}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
