import * as React from "react";
import type { CodeNotification, StoryProps } from "./notification-types";
import { cx } from "./notification-shared";
export function CodeDetail({
  item,
  play,
  delay,
  reduced,
}: StoryProps & { item: CodeNotification }) {
  const animate = play > 0 && !reduced,
    digits = Array.from(item.code);
  const total = React.useMemo(
    () =>
      Math.max(
        0,
        Math.round(
          item.expiresIn ??
            (item.expiresAt
              ? (Date.parse(item.expiresAt) - Date.now()) / 1000
              : 0),
        ),
      ),
    [item.id, item.code, item.expiresIn, item.expiresAt],
  );
  // Replaying a card never extends the code's real remaining lifetime.
  const deadline = React.useMemo(
    () =>
      item.expiresAt ? Date.parse(item.expiresAt) : Date.now() + total * 1000,
    [item.id, item.code, item.expiresAt, total],
  );
  const [left, setLeft] = React.useState(total);
  const [copy, setCopy] = React.useState<"idle" | "done" | "blocked">("idle");
  const slotsRef = React.useRef<HTMLSpanElement>(null);
  React.useEffect(() => {
    const slots = Array.from(
      slotsRef.current?.querySelectorAll("[data-digit]") ?? [],
    );
    const settle = () =>
      slots.forEach((slot, i) => {
        slot.textContent = item.code[i] ?? "";
      });
    if (!animate) {
      settle();
      return;
    }
    const timers: number[] = [],
      spins: number[] = [],
      animations: Animation[] = [];
    slots.forEach((slot, i) => {
      slot.textContent = "";
      timers.push(
        window.setTimeout(
          () => {
            const spin = window.setInterval(() => {
              slot.textContent = String(Math.floor(Math.random() * 10));
            }, 45);
            spins.push(spin);
            timers.push(
              window.setTimeout(() => {
                window.clearInterval(spin);
                slot.textContent = item.code[i] ?? "";
                const animation = slot.parentElement?.animate?.(
                  [{ transform: "scale(1.2)" }, { transform: "scale(1)" }],
                  { duration: 260, easing: "cubic-bezier(0.3, 1.6, 0.5, 1)" },
                );
                if (animation) animations.push(animation);
              }, 320),
            );
          },
          Math.max(80, delay) + i * 110,
        ),
      );
    });
    return () => {
      timers.forEach(window.clearTimeout);
      spins.forEach(window.clearInterval);
      animations.forEach((animation) => animation.cancel());
      settle();
    };
  }, [play, animate, delay, item.code]);
  React.useEffect(() => {
    let timer = 0;
    const update = () => {
      const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      setLeft(remaining);
      if (remaining === 0) window.clearInterval(timer);
    };
    update();
    if (deadline <= Date.now() || (total <= 0 && !item.expiresAt)) return;
    timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [deadline, total, item.expiresAt]);
  React.useEffect(() => {
    if (copy === "idle") return;
    const timer = window.setTimeout(() => setCopy("idle"), 1600);
    return () => window.clearTimeout(timer);
  }, [copy]);
  const expired = (total > 0 || Boolean(item.expiresAt)) && left === 0,
    half = Math.ceil(digits.length / 2);
  return (
    <div data-detail="code" data-left={left}>
      <div className="flex flex-wrap items-center gap-2">
        <span
          ref={slotsRef}
          role="img"
          aria-label={`Codice ${digits.join(" ")}`}
          className="flex max-w-full flex-wrap items-center gap-1"
        >
          {digits.map((digit, i) => (
            <React.Fragment key={i}>
              {i === half && (
                <span aria-hidden className="mx-0.5 h-px w-2 bg-border" />
              )}
              <span
                className={cx(
                  "grid h-8 w-6 shrink-0 place-items-center rounded-md border border-border bg-background font-mono text-base font-semibold text-foreground",
                  expired && "opacity-40",
                )}
              >
                <span data-digit>{digit}</span>
              </span>
            </React.Fragment>
          ))}
        </span>
        <button
          type="button"
          data-copy={copy}
          disabled={expired}
          onClick={(event) => {
            event.stopPropagation();
            if (!navigator.clipboard) {
              setCopy("blocked");
              return;
            }
            void navigator.clipboard.writeText(item.code).then(
              () => setCopy("done"),
              () => setCopy("blocked"),
            );
          }}
          className="relative z-[1] ml-auto h-7 shrink-0 rounded-full border border-border bg-background px-2.5 text-xs font-medium text-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40"
        >
          {copy === "done"
            ? "Copiato"
            : copy === "blocked"
              ? "Copia bloccata"
              : "Copia"}
        </button>
      </div>
      {total > 0 && (
        <div className="mt-2 flex items-center gap-2">
          <span className="h-1 flex-1 overflow-hidden rounded-full bg-muted">
            <span
              data-expiry
              className="block h-full rounded-full"
              style={{
                width: `${Math.min(1, left / total) * 100}%`,
                background: "currentColor",
                transition: reduced ? "none" : "width 1s linear",
              }}
            />
          </span>
          <span className="text-[11px] tabular-nums text-muted-foreground">
            {expired
              ? "Scaduto"
              : `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`}
          </span>
        </div>
      )}
    </div>
  );
}
