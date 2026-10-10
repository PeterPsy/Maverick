import * as React from "react";
import { Package } from "lucide-react";
import type {
  MessageNotification,
  DeliveryNotification,
  StoryProps,
} from "./notification-types";
import { cx, initialsOf, TINT } from "./notification-shared";

export function MessageDetail({
  item,
  play,
  delay,
  reduced,
}: StoryProps & { item: MessageNotification }) {
  const animate = play > 0 && !reduced;
  const [typing, setTyping] = React.useState(animate);
  const wordsRef = React.useRef<HTMLSpanElement>(null);
  const dotsRef = React.useRef<HTMLSpanElement>(null);
  React.useEffect(() => {
    if (!animate) {
      setTyping(false);
      return;
    }
    setTyping(true);
    const timer = window.setTimeout(() => setTyping(false), delay + 1000);
    return () => window.clearTimeout(timer);
  }, [play, animate, delay]);
  React.useEffect(() => {
    if (!typing) return;
    const bounce = Array.from(dotsRef.current?.children ?? []).map((dot, i) =>
      dot.animate?.(
        [
          { transform: "translateY(0)", opacity: 0.35 },
          { transform: "translateY(-3px)", opacity: 1 },
          { transform: "translateY(0)", opacity: 0.35 },
        ],
        {
          duration: 760,
          delay: i * 130,
          iterations: Infinity,
          easing: "ease-in-out",
        },
      ),
    );
    return () => bounce.forEach((animation) => animation?.cancel());
  }, [typing]);
  React.useEffect(() => {
    if (!animate || typing) return;
    const reveal = Array.from(wordsRef.current?.children ?? []).map((word, i) =>
      word.animate?.(
        [
          { opacity: 0, transform: "translateY(4px)", filter: "blur(2px)" },
          { opacity: 1, transform: "none", filter: "blur(0)" },
        ],
        { duration: 260, delay: i * 40, easing: "ease-out", fill: "backwards" },
      ),
    );
    return () => reveal.forEach((animation) => animation?.cancel());
  }, [typing, animate]);
  return (
    <div data-detail="message" className="flex items-end gap-2">
      <span
        aria-hidden
        className="grid size-7 shrink-0 place-items-center rounded-full text-[10px] font-semibold"
        style={{ background: TINT }}
      >
        {initialsOf(item.from)}
      </span>
      <div className="min-w-0 rounded-2xl rounded-bl-md bg-muted px-3 py-2 text-[13px] leading-snug text-foreground">
        {typing ? (
          <>
            <span className="sr-only">{item.text}</span>
            <span
              ref={dotsRef}
              aria-hidden
              data-typing
              className="flex h-[18px] items-center gap-1"
            >
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className="size-1.5 rounded-full bg-muted-foreground"
                />
              ))}
            </span>
          </>
        ) : (
          <span ref={wordsRef} data-text>
            {item.text
              .split(/\s+/)
              .filter(Boolean)
              .map((word, i) => (
                <React.Fragment key={i}>
                  {i > 0 && " "}
                  <span className="inline-block">{word}</span>
                </React.Fragment>
              ))}
          </span>
        )}
      </div>
    </div>
  );
}

export function DeliveryDetail({
  item,
  play,
  delay,
  reduced,
}: StoryProps & { item: DeliveryNotification }) {
  const animate = play > 0 && !reduced;
  const n = Math.max(1, item.steps.length);
  const step = Math.min(Math.max(0, Math.round(item.step)), n - 1);
  const at = (i: number) => (n > 1 ? (i / (n - 1)) * 100 : 100);
  const [progress, setProgress] = React.useState(() => at(step));
  const [moving, setMoving] = React.useState(false);
  const parcelRef = React.useRef<HTMLSpanElement>(null);
  React.useEffect(() => {
    const target = n > 1 ? (step / (n - 1)) * 100 : 100;
    if (!animate) {
      setMoving(false);
      setProgress(target);
      return;
    }
    const start = Math.max(80, delay);
    setMoving(false);
    setProgress(n > 1 ? (Math.max(0, step - 1) / (n - 1)) * 100 : 0);
    const go = window.setTimeout(() => {
      setMoving(true);
      setProgress(target);
    }, start);
    let bounce: Animation | undefined;
    const land = window.setTimeout(() => {
      bounce = parcelRef.current?.animate?.(
        [
          { transform: "translateY(0) rotate(0deg)" },
          { transform: "translateY(-6px) rotate(-8deg)" },
          { transform: "translateY(0) rotate(0deg)" },
          { transform: "translateY(-2px) rotate(0deg)" },
          { transform: "translateY(0) rotate(0deg)" },
        ],
        { duration: 480, easing: "ease-out" },
      );
    }, start + 1040);
    return () => {
      window.clearTimeout(go);
      window.clearTimeout(land);
      bounce?.cancel();
    };
  }, [play, animate, delay, step, n]);
  const transition = moving
    ? "left 1100ms cubic-bezier(0.55, 0, 0.25, 1), width 1100ms cubic-bezier(0.55, 0, 0.25, 1)"
    : "none";
  return (
    <div data-detail="delivery" className="px-2" aria-label={item.steps[step]}>
      <div className="relative h-6">
        <span className="absolute inset-x-0 top-1/2 h-[3px] -translate-y-1/2 rounded-full bg-muted" />
        <span
          data-fill
          className="absolute left-0 top-1/2 h-[3px] -translate-y-1/2 rounded-full"
          style={{
            width: `${progress}%`,
            background: "currentColor",
            transition,
          }}
        />
        {item.steps.map((label, i) => {
          const reached = at(i) <= progress + 0.01;
          return (
            <span
              key={`${label}-${i}`}
              data-stop={i}
              data-reached={reached ? "" : undefined}
              className={cx(
                "absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-card",
                !reached && "bg-muted-foreground/30",
              )}
              style={{
                left: `${at(i)}%`,
                background: reached ? "currentColor" : undefined,
              }}
            />
          );
        })}
        <span
          data-parcel
          className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2"
          style={{ left: `${progress}%`, transition }}
        >
          <span
            ref={parcelRef}
            className="grid size-5 place-items-center rounded-md shadow-sm"
            style={{ background: "currentColor" }}
          >
            <Package aria-hidden className="size-3 text-white" />
          </span>
        </span>
      </div>
      <div className="relative mt-1 h-3.5">
        {item.steps.map((label, i) => (
          <span
            key={`${label}-${i}`}
            className={cx(
              "absolute top-0 whitespace-nowrap text-[10px] leading-none",
              i === step
                ? "font-medium text-foreground"
                : "text-muted-foreground",
            )}
            style={{
              left: `${at(i)}%`,
              transform: `translateX(${i === 0 ? "0" : i === n - 1 ? "-100%" : "-50%"})`,
            }}
          >
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}
