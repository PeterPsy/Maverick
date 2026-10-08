import type * as React from "react";

export type SpanKind = "agent" | "model" | "tool" | "io";
export type SpanStatus = "ok" | "error" | "cached" | "running" | "waiting";

export interface TraceSpan {
  id: string;
  label: string;
  /** Offsets in milliseconds from the first action. Active spans end at the current time. */
  start: number;
  end: number;
  kind?: SpanKind;
  status?: SpanStatus;
  parentId?: string;
  detail?: string;
  tokens?: number;
  attempt?: number;
}

export interface AgentTraceProps extends React.ComponentProps<"div"> {
  spans: TraceSpan[];
  duration?: number;
  runId?: string;
  model?: string;
  defaultTime?: number;
  autoPlay?: boolean;
  loop?: boolean;
  speed?: number;
  holdMs?: number;
  showRuler?: boolean;
  showTransport?: boolean;
  /** Allow seeking and scrubbing; row selection remains available when disabled. */
  interactive?: boolean;
  /** Resume the animation from the chosen time after dragging the graph. */
  replayOnSeek?: boolean;
  showTokens?: boolean;
  labelWidth?: number;
  rowHeight?: number;
  onSpanSelect?: (span: TraceSpan) => void;
  /** Follow streamed elapsed time instead of simulating progress. */
  currentTime?: number;
  live?: boolean;
  selectedSpanId?: string | null;
  detailsId?: string;
}

export interface LaidSpan extends TraceSpan { depth: number; dur: number }
export type RowState = "queued" | "running" | "waiting" | "done" | "error";
export interface RowHandle {
  el: HTMLElement;
  meta: HTMLElement | null;
  dur: HTMLElement | null;
  status: HTMLElement | null;
  span: LaidSpan;
}

export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
export const formatMs = (ms: number) => ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)}s`;
const groupDigits = (n: number) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
export const metaText = (span: LaidSpan, p: number, showTokens: boolean) =>
  span.tokens != null && showTokens ? `${groupDigits(Math.round(span.tokens * p))} tk`
    : p >= 1 && span.status !== "running" && span.status !== "waiting" ? (span.detail ?? "") : "";

export function rowState(span: LaidSpan, time: number): RowState {
  if (time < span.start) return "queued";
  if (time < span.end) return "running";
  if (span.status === "running" || span.status === "waiting") return span.status;
  return span.status === "error" ? "error" : "done";
}

export const statusWord = (span: LaidSpan, state: RowState) =>
  state === "done" && span.status === "cached" ? "served from cache"
    : ({ queued: "queued", running: "running", waiting: "awaiting confirmation", done: "succeeded", error: "failed" })[state];

/** Children below their parent, siblings by start time; tolerate cycles and orphans. */
export function layout(spans: TraceSpan[]): LaidSpan[] {
  const children = new Map<string, TraceSpan[]>();
  const ids = new Set(spans.map(s => s.id));
  for (const s of spans) {
    const key = s.parentId && s.parentId !== s.id && ids.has(s.parentId) ? s.parentId : "";
    children.set(key, [...(children.get(key) ?? []), s]);
  }
  const out: LaidSpan[] = [];
  const seen = new Set<string>();
  const walk = (parent: string, depth: number) => {
    for (const kid of (children.get(parent) ?? []).slice().sort((a, b) => a.start - b.start)) {
      if (seen.has(kid.id)) continue;
      seen.add(kid.id);
      out.push({ ...kid, depth, dur: Math.max(0, kid.end - kid.start) });
      walk(kid.id, depth + 1);
    }
  };
  walk("", 0);
  for (const s of spans) if (!seen.has(s.id)) { walk(s.parentId ?? "", 0); }
  return out;
}

const NICE_TICKS = [50, 100, 250, 500, 1000, 2000, 2500, 5000, 10_000, 30_000, 60_000];
export function traceTicks(total: number): number[] {
  const step = NICE_TICKS.find(t => total / t <= 8) ?? total / 4;
  const out: number[] = [];
  for (let t = step; t < total; t += step) out.push(t);
  return out;
}
