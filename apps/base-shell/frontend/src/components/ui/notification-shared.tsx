import * as React from "react";
import {
  Bell,
  CalendarDays,
  Car,
  CreditCard,
  Heart,
  MessageCircle,
  Package,
  Plane,
  ShieldCheck,
} from "lucide-react";
import type { Entry, NotificationKind } from "./notification-types";
import { cn } from "../../lib/utils";
export const ENTER_MS = 460;
export const LEAVE_MS = 340;
export const TINT = "color-mix(in oklab, currentColor 15%, transparent)";
export const DEFAULT_HEIGHT = "min(440px, calc(100svh - 12rem))";
export const ICONS = {
  generic: Bell,
  message: MessageCircle,
  delivery: Package,
  ride: Car,
  payment: CreditCard,
  calendar: CalendarDays,
  code: ShieldCheck,
  flight: Plane,
  fitness: Heart,
};
export function cx(...classes: (string | false | null | undefined)[]) {
  return cn(...classes);
}
export function initialsOf(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]!.toUpperCase())
    .join("");
}
export function staticEntry(
  id: string,
  generation: number,
  fresh = false,
  delay = 0,
): Entry {
  return {
    id,
    key: `${id}:${generation}`,
    play: 0,
    fresh,
    leaving: false,
    arrived: false,
    delay,
    leaveDelay: 0,
  };
}
export function useReducedMotion() {
  const [reduced, setReduced] = React.useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  React.useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return reduced;
}
export function AppTile({
  kind,
  accent,
  icon,
  play,
  delay,
  reduced,
}: {
  kind: NotificationKind;
  accent?: string;
  icon?: React.ReactNode;
  play: number;
  delay: number;
  reduced: boolean;
}) {
  const ringRef = React.useRef<HTMLSpanElement>(null);
  React.useEffect(() => {
    if (play === 0 || reduced) return;
    const animation = ringRef.current?.animate?.(
      [
        { transform: "scale(1)", opacity: 0.6 },
        { transform: "scale(1.75)", opacity: 0 },
      ],
      { duration: 900, delay, easing: "cubic-bezier(0.2, 0.7, 0.3, 1)" },
    );
    return () => animation?.cancel();
  }, [play, delay, reduced]);
  const Icon = ICONS[kind];
  return (
    <span
      data-tile
      className={cx(
        "relative grid size-9 shrink-0 place-items-center rounded-xl",
        !accent && "text-primary",
      )}
      style={{ color: accent, background: TINT }}
    >
      {icon ?? <Icon className="size-[18px]" aria-hidden strokeWidth={1.8} />}
      <span
        ref={ringRef}
        aria-hidden
        className="pointer-events-none absolute inset-0 rounded-xl border-2 border-current opacity-0"
      />
    </span>
  );
}
