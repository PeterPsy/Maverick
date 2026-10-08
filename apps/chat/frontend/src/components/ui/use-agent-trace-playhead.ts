import * as React from "react";
import { clamp, formatMs, metaText, rowState, statusWord, type RowHandle } from "./agent-trace-model";

export const useTraceLayoutEffect = typeof window === "undefined" ? React.useEffect : React.useLayoutEffect;

interface PlayheadOptions {
  total: number;
  currentTime?: number;
  live: boolean;
  defaultTime: number;
  autoPlay: boolean;
  loop: boolean;
  speed: number;
  holdMs: number;
  showTokens: boolean;
}

/** Replay writes to row DOM handles; streamed time always comes from the runtime projection. */
export function useAgentTracePlayhead(options: PlayheadOptions) {
  const rootRef = React.useRef<HTMLDivElement>(null);
  const railRef = React.useRef<HTMLDivElement>(null);
  const clockRef = React.useRef<HTMLSpanElement>(null);
  const statusRef = React.useRef<HTMLSpanElement>(null);
  const rowsRef = React.useRef<(RowHandle | null)[]>([]);
  const timeRef = React.useRef(options.currentTime ?? options.defaultTime);
  const playingRef = React.useRef(false);
  const followingRef = React.useRef(options.currentTime != null);
  const [playing, setPlaying] = React.useState(false);
  const [following, setFollowing] = React.useState(followingRef.current);
  const seekRef = React.useRef<(ms: number) => void>(() => {});
  const paintRef = React.useRef<() => void>(() => {});
  const runRef = React.useRef<() => void>(() => {});
  const haltRef = React.useRef<() => void>(() => {});
  const opts = React.useRef(options);
  useTraceLayoutEffect(() => { opts.current = options; });

  useTraceLayoutEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    let raf = 0;
    let last = 0;
    let holdUntil = 0;
    let onScreen = true;
    const paint = () => {
      const o = opts.current;
      const t = timeRef.current;
      root.style.setProperty("--t", (t / o.total).toFixed(5));
      for (const row of rowsRef.current) {
        if (!row) continue;
        const { span } = row;
        const p = span.dur > 0 ? clamp((t - span.start) / span.dur, 0, 1) : t >= span.start ? 1 : 0;
        const state = rowState(span, t);
        const progress = p.toFixed(4);
        if (row.el.style.getPropertyValue("--p") !== progress) row.el.style.setProperty("--p", progress);
        if (row.el.dataset.state !== state) row.el.dataset.state = state;
        const status = statusWord(span, state);
        if (row.status && row.status.textContent !== status) row.status.textContent = status;
        const dur = state === "queued" ? "" : formatMs(span.dur * p);
        if (row.dur && row.dur.textContent !== dur) row.dur.textContent = dur;
        const meta = state === "queued" ? "" : metaText(span, p, o.showTokens);
        if (row.meta && row.meta.textContent !== meta) row.meta.textContent = meta;
      }
      if (clockRef.current) clockRef.current.textContent = `${(t / 1000).toFixed(2)}s / ${(o.total / 1000).toFixed(2)}s`;
      const atEnd = t >= o.total;
      const active = rowsRef.current.filter(row => row?.span.status === "running" || row?.span.status === "waiting");
      const failed = rowsRef.current.some(row => row?.span.status === "error");
      const runState = atEnd && !o.live ? (failed ? "error" : "complete")
        : atEnd && active.length && active.every(row => row?.span.status === "waiting") ? "waiting" : "running";
      root.dataset.run = runState;
      if (statusRef.current) statusRef.current.textContent = ({ complete: "Completed", error: "Failed", waiting: "Awaiting confirmation", running: "Running" })[runState];
      const rail = railRef.current;
      if (rail && !playingRef.current) {
        rail.setAttribute("aria-valuenow", String(Math.round(t)));
        rail.setAttribute("aria-valuetext", `${formatMs(t)} of ${formatMs(o.total)}`);
      }
    };
    const frame = (now: number) => {
      raf = 0;
      const o = opts.current;
      const dt = Math.min(now - (last || now), 100);
      last = now;
      if (holdUntil > 0) {
        if (now >= holdUntil) { holdUntil = 0; timeRef.current = 0; }
      } else {
        timeRef.current += dt * Math.max(0.01, o.speed);
        if (timeRef.current >= o.total) {
          timeRef.current = o.total;
          if (o.loop && !o.live) holdUntil = now + o.holdMs;
          else {
            playingRef.current = false; setPlaying(false);
            if (o.currentTime != null) {
              followingRef.current = true; setFollowing(true);
              timeRef.current = clamp(o.currentTime, 0, o.total);
            }
          }
        }
      }
      paint();
      if (playingRef.current) raf = requestAnimationFrame(frame);
    };
    const start = () => {
      if (raf || !playingRef.current || !onScreen || document.hidden) return;
      last = 0;
      raf = requestAnimationFrame(frame);
    };
    const halt = () => { cancelAnimationFrame(raf); raf = 0; };
    runRef.current = start;
    haltRef.current = halt;
    paintRef.current = paint;
    seekRef.current = ms => {
      timeRef.current = clamp(ms, 0, opts.current.total);
      holdUntil = 0; last = 0; paint();
    };
    if (media.matches && !followingRef.current) timeRef.current = opts.current.total;
    else if (options.autoPlay && !followingRef.current) {
      playingRef.current = true; setPlaying(true);
    }
    paint();
    const onVisibility = () => document.hidden ? halt() : start();
    const onMedia = () => {
      if (!media.matches) return;
      playingRef.current = false; setPlaying(false); halt();
      seekRef.current(opts.current.currentTime ?? opts.current.total);
    };
    const io = new IntersectionObserver(([entry]) => {
      onScreen = entry?.isIntersecting ?? true;
      if (onScreen) start(); else halt();
    });
    io.observe(root);
    document.addEventListener("visibilitychange", onVisibility);
    media.addEventListener("change", onMedia);
    start();
    return () => {
      halt(); io.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      media.removeEventListener("change", onMedia);
      runRef.current = () => {}; haltRef.current = () => {}; seekRef.current = () => {}; paintRef.current = () => {};
    };
  }, [options.autoPlay]);

  const appliedDefault = React.useRef(options.defaultTime);
  useTraceLayoutEffect(() => {
    if (appliedDefault.current === options.defaultTime) return;
    appliedDefault.current = options.defaultTime;
    seekRef.current(options.defaultTime);
  }, [options.defaultTime]);

  // Called after React has registered the latest rows, including new streamed actions.
  const repaint = () => {
    timeRef.current = clamp(followingRef.current ? opts.current.currentTime ?? opts.current.total : timeRef.current, 0, opts.current.total);
    paintRef.current();
  };
  const stopFollowing = () => { followingRef.current = false; setFollowing(false); };
  const seek = (ms: number) => { stopFollowing(); seekRef.current(ms); };
  const pause = () => {
    playingRef.current = false; setPlaying(false); haltRef.current();
  };
  const resume = () => {
    if (timeRef.current >= opts.current.total) {
      if (opts.current.currentTime != null) followLive();
      return;
    }
    stopFollowing();
    playingRef.current = true; setPlaying(true); runRef.current();
  };
  const togglePlay = () => {
    if (followingRef.current && opts.current.live) {
      stopFollowing(); return;
    }
    stopFollowing();
    const next = !playingRef.current;
    if (next && timeRef.current >= opts.current.total) timeRef.current = 0;
    playingRef.current = next; setPlaying(next);
    seekRef.current(timeRef.current);
    if (next) runRef.current(); else haltRef.current();
  };
  const followLive = () => {
    playingRef.current = false; setPlaying(false); haltRef.current();
    followingRef.current = true; setFollowing(true); repaint();
  };
  return { rootRef, railRef, clockRef, statusRef, rowsRef, timeRef, playing, following, repaint, seek, pause, resume, togglePlay, followLive };
}
