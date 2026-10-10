import * as React from "react";
import { Plane } from "lucide-react";
import type {
  FlightNotification,
  FitnessNotification,
  StoryProps,
} from "./notification-types";
import { cx } from "./notification-shared";
const FLAP_CHARS = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
export function FlightDetail({
  item,
  play,
  delay,
  reduced,
}: StoryProps & { item: FlightNotification }) {
  const animate = play > 0 && !reduced,
    target = item.gate.toUpperCase();
  const from = (item.previousGate ?? item.gate)
    .toUpperCase()
    .slice(-target.length)
    .padStart(target.length, " ");
  const flapsRef = React.useRef<HTMLSpanElement>(null),
    planeRef = React.useRef<HTMLSpanElement>(null);
  React.useEffect(() => {
    const cells = Array.from(
      flapsRef.current?.querySelectorAll("[data-flap]") ?? [],
    );
    const settle = () =>
      cells.forEach((cell, i) => {
        cell.textContent = target[i] ?? " ";
      });
    if (!animate) {
      settle();
      return;
    }
    const start = Math.max(80, delay),
      timers: number[] = [],
      flips: Animation[] = [];
    cells.forEach((cell, i) => {
      cell.textContent = from[i] ?? " ";
      const a = FLAP_CHARS.indexOf(from[i] ?? " "),
        b = FLAP_CHARS.indexOf(target[i] ?? " ");
      const count = Math.min(
        a < 0 || b < 0 ? 1 : (b - a + FLAP_CHARS.length) % FLAP_CHARS.length,
        8,
      );
      for (let s = 0; s < count; s++) {
        timers.push(
          window.setTimeout(
            () => {
              cell.textContent =
                b < 0
                  ? target[i]
                  : FLAP_CHARS[
                      (b - (count - 1 - s) + FLAP_CHARS.length) %
                        FLAP_CHARS.length
                    ]!;
              const flip = cell.animate?.(
                [
                  { transform: "rotateX(-88deg)", filter: "brightness(1.8)" },
                  { transform: "rotateX(0deg)", filter: "brightness(1)" },
                ],
                { duration: 70, easing: "ease-out" },
              );
              if (flip) flips.push(flip);
            },
            start + 200 + i * 90 + s * 75,
          ),
        );
      }
    });
    const taxi = planeRef.current?.animate?.(
      [{ left: "10%" }, { left: "50%" }],
      {
        duration: 900,
        delay: start,
        easing: "cubic-bezier(0.3, 0.7, 0.2, 1)",
        fill: "backwards",
      },
    );
    return () => {
      timers.forEach(window.clearTimeout);
      flips.forEach((flip) => flip.cancel());
      taxi?.cancel();
      settle();
    };
  }, [play, animate, delay, target, from]);
  return (
    <div data-detail="flight" className="flex flex-wrap items-center gap-3">
      <div className="flex min-w-0 flex-1 items-center gap-2 font-mono text-sm font-semibold text-foreground">
        <span>{item.from}</span>
        <span className="relative h-px flex-1 border-t border-dashed border-muted-foreground/40">
          <span
            ref={planeRef}
            className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rotate-45"
          >
            <Plane aria-hidden className="size-3.5" />
          </span>
        </span>
        <span>{item.to}</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          Gate
        </span>
        <span
          ref={flapsRef}
          data-gate={item.gate}
          aria-label={item.gate}
          className="flex gap-0.5 [perspective:200px]"
        >
          {Array.from(target).map((ch, i) => (
            <span
              key={i}
              className="relative grid h-7 w-5 place-items-center overflow-hidden rounded-[4px] bg-foreground font-mono text-sm font-bold text-background"
            >
              <span data-flap className="block">
                {ch}
              </span>
              <span
                aria-hidden
                className="pointer-events-none absolute inset-x-0 top-1/2 h-px bg-background/30"
              />
            </span>
          ))}
        </span>
        {item.previousGate && (
          <span className="text-[11px] text-muted-foreground line-through">
            {item.previousGate}
          </span>
        )}
      </div>
    </div>
  );
}
export function FitnessDetail({
  item,
  play,
  delay,
  reduced,
}: StoryProps & { item: FitnessNotification }) {
  const animate = play > 0 && !reduced,
    ratio =
      item.goal > 0 ? Math.min(1, Math.max(0, item.value / item.goal)) : 0;
  const circumference = 2 * Math.PI * 15,
    streak = Math.max(0, Math.min(7, Math.round(item.streak ?? 0)));
  const [drawn, setDrawn] = React.useState(!animate);
  const ringRef = React.useRef<SVGSVGElement>(null),
    burstRef = React.useRef<HTMLSpanElement>(null),
    daysRef = React.useRef<HTMLSpanElement>(null);
  React.useEffect(() => {
    if (!animate) {
      setDrawn(true);
      return;
    }
    setDrawn(false);
    const start = Math.max(80, delay),
      timers = [window.setTimeout(() => setDrawn(true), start)],
      effects: Animation[] = [];
    const keep = (animation: Animation | undefined) => {
      if (animation) effects.push(animation);
    };
    if (ratio >= 1)
      timers.push(
        window.setTimeout(() => {
          keep(
            ringRef.current?.animate?.(
              [
                { transform: "scale(1)" },
                { transform: "scale(1.12)" },
                { transform: "scale(1)" },
              ],
              { duration: 380, easing: "ease-out" },
            ),
          );
          const dots = Array.from(burstRef.current?.children ?? []);
          dots.forEach((dot, i) => {
            const angle = (i / dots.length) * Math.PI * 2;
            keep(
              dot.animate?.(
                [
                  {
                    transform: `translate(${Math.cos(angle) * 17}px, ${Math.sin(angle) * 17}px) scale(1)`,
                    opacity: 1,
                  },
                  {
                    transform: `translate(${Math.cos(angle) * 28}px, ${Math.sin(angle) * 28}px) scale(0.3)`,
                    opacity: 0,
                  },
                ],
                { duration: 600, easing: "cubic-bezier(0.2, 0.7, 0.3, 1)" },
              ),
            );
          });
          const today =
            streak > 0 ? daysRef.current?.children[streak - 1] : undefined;
          keep(
            today?.animate?.(
              [
                { transform: "scale(0)" },
                { transform: "scale(1.35)" },
                { transform: "scale(1)" },
              ],
              { duration: 420, easing: "ease-out" },
            ),
          );
        }, start + 1000),
      );
    return () => {
      timers.forEach(window.clearTimeout);
      effects.forEach((effect) => effect.cancel());
    };
  }, [play, animate, delay, ratio, streak]);
  return (
    <div
      data-detail="fitness"
      data-drawn={drawn ? "" : undefined}
      className="flex items-center gap-3"
    >
      <span className="relative grid size-11 shrink-0 place-items-center">
        <svg ref={ringRef} viewBox="0 0 40 40" aria-hidden className="size-11">
          <g transform="rotate(-90 20 20)">
            <circle
              cx={20}
              cy={20}
              r={15}
              fill="none"
              stroke="currentColor"
              strokeOpacity={0.16}
              strokeWidth={5}
            />
            <circle
              data-ring
              cx={20}
              cy={20}
              r={15}
              fill="none"
              stroke="currentColor"
              strokeWidth={5}
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={circumference * (1 - (drawn ? ratio : 0))}
              style={{
                transition:
                  animate && drawn
                    ? "stroke-dashoffset 1100ms cubic-bezier(0.3, 0.7, 0.2, 1)"
                    : "none",
              }}
            />
          </g>
        </svg>
        <span
          ref={burstRef}
          aria-hidden
          className="pointer-events-none absolute inset-0 grid place-items-center"
        >
          {Array.from({ length: 8 }, (_, i) => (
            <span
              key={i}
              className="absolute size-1.5 rounded-full opacity-0"
              style={{ background: "currentColor" }}
            />
          ))}
        </span>
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold tabular-nums text-foreground">
          {item.value.toLocaleString(item.locale ?? "it-IT")}
          <span className="font-normal text-muted-foreground">
            {" "}
            / {item.goal.toLocaleString(item.locale ?? "it-IT")} {item.unit}
          </span>
        </div>
        {streak > 0 && (
          <span
            ref={daysRef}
            role="img"
            aria-label={`${streak} giorni consecutivi`}
            className="mt-1.5 flex gap-1"
          >
            {Array.from({ length: 7 }, (_, i) => (
              <span
                key={i}
                className={cx("size-2 rounded-full", i >= streak && "bg-muted")}
                style={i < streak ? { background: "currentColor" } : undefined}
              />
            ))}
          </span>
        )}
      </div>
    </div>
  );
}
