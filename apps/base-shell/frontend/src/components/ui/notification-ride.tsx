import * as React from "react";
import type { RideNotification, StoryProps } from "./notification-types";
import { TINT } from "./notification-shared";

const ROUTE = "M12 44 C 44 44, 54 14, 98 17 S 158 46, 198 35 S 248 13, 284 16";
export function RideDetail({
  item,
  play,
  delay,
  reduced,
}: StoryProps & { item: RideNotification }) {
  const animate = play > 0 && !reduced;
  const pathRef = React.useRef<SVGPathElement>(null);
  const trailRef = React.useRef<SVGPathElement>(null);
  const carRef = React.useRef<SVGGElement>(null);
  const pinRef = React.useRef<SVGCircleElement>(null);
  const [eta, setEta] = React.useState(item.minutes);
  React.useLayoutEffect(() => {
    const path = pathRef.current,
      trail = trailRef.current,
      car = carRef.current;
    if (!path || !trail || !car || !path.getTotalLength) return;
    const total = path.getTotalLength();
    trail.style.strokeDasharray = `${total}`;
    const place = (t: number) => {
      const length = total * t,
        point = path.getPointAtLength(length),
        ahead = path.getPointAtLength(Math.min(total, length + 1));
      const angle =
        (Math.atan2(ahead.y - point.y, ahead.x - point.x) * 180) / Math.PI;
      car.setAttribute(
        "transform",
        `translate(${point.x} ${point.y}) rotate(${angle})`,
      );
      car.style.opacity = "1";
      trail.style.strokeDashoffset = `${total - length}`;
    };
    if (!animate) {
      place(0.78);
      setEta(item.minutes);
      return;
    }
    place(0.05);
    setEta(item.minutes + 3);
    const pulse = pinRef.current?.animate?.(
      [
        { transform: "scale(1)", opacity: 0.35 },
        { transform: "scale(2.2)", opacity: 0 },
      ],
      { duration: 1100, delay, iterations: 2, easing: "ease-out" },
    );
    const start = performance.now() + Math.max(80, delay);
    let frame = 0;
    const tick = (now: number) => {
      const k = Math.min(1, Math.max(0, (now - start) / 1700));
      const eased = k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2;
      place(0.05 + 0.73 * eased);
      setEta(item.minutes + Math.round(3 * (1 - eased)));
      if (k < 1) frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);
    return () => {
      window.cancelAnimationFrame(frame);
      pulse?.cancel();
    };
  }, [play, animate, delay, item.minutes]);
  return (
    <div data-detail="ride" data-eta={eta}>
      <div className="relative overflow-hidden rounded-xl border border-border bg-muted/60">
        <svg viewBox="0 0 300 60" aria-hidden className="block h-auto w-full">
          <g
            className="text-border"
            stroke="currentColor"
            strokeWidth={6}
            strokeLinecap="round"
            fill="none"
          >
            <path d="M-10 30 H 310" />
            <path d="M70 -10 V 70" />
            <path d="M176 -10 V 70" />
            <path d="M232 -10 L 300 54" />
          </g>
          <path
            ref={pathRef}
            d={ROUTE}
            fill="none"
            className="text-muted-foreground"
            stroke="currentColor"
            strokeWidth={2}
            strokeDasharray="1 5"
            strokeLinecap="round"
            opacity={0.7}
          />
          <path
            ref={trailRef}
            d={ROUTE}
            fill="none"
            stroke="currentColor"
            strokeWidth={3}
            strokeLinecap="round"
          />
          <g transform="translate(284 16)">
            <circle
              ref={pinRef}
              r={6}
              fill="currentColor"
              opacity={0}
              style={{ transformBox: "fill-box", transformOrigin: "center" }}
            />
            <circle
              r={4.5}
              fill="currentColor"
              stroke="white"
              strokeWidth={2}
            />
          </g>
          <g ref={carRef} data-car style={{ opacity: 0 }}>
            <rect
              x={-8}
              y={-5}
              width={16}
              height={10}
              rx={3.5}
              fill="currentColor"
            />
            <rect
              x={2}
              y={-3.5}
              width={3.5}
              height={7}
              rx={1.2}
              fill="white"
              opacity={0.85}
            />
          </g>
        </svg>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
        <span
          data-eta-chip
          className="rounded-full px-2 py-0.5 font-semibold tabular-nums"
          style={{ background: TINT }}
        >
          <span className="text-foreground">{eta} min</span>
        </span>
        <span className="rounded-full border border-border px-2 py-0.5 font-mono font-medium text-foreground">
          {item.plate}
        </span>
        <span className="text-muted-foreground">{item.vehicle}</span>
      </div>
    </div>
  );
}
