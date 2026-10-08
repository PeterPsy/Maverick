"use client";

import * as React from "react";
import { Pause, Play, Radio } from "lucide-react";
import { cn } from "@/lib/utils";
import { layout, traceTicks, type AgentTraceProps, type LaidSpan, type RowHandle } from "./agent-trace-model";
import { TraceSpanRow } from "./agent-trace-row";
import { useAgentTracePlayhead, useTraceLayoutEffect } from "./use-agent-trace-playhead";
import "./agent-trace.css";
export type { AgentTraceProps, TraceSpan, SpanKind, SpanStatus } from "./agent-trace-model";
export { TraceSpanRow } from "./agent-trace-row";

/** A streamed agent run on a navigable time axis, with replay after completion. */
export function AgentTrace({
  spans, duration, runId = "run", model, defaultTime = 0, autoPlay = true,
  loop = false, speed = 1, holdMs = 900, showRuler = true, showTransport = true,
  interactive = true, replayOnSeek = false,
  showTokens = true, labelWidth = 200, rowHeight = 34, onSpanSelect,
  currentTime, live = false, selectedSpanId, detailsId, className, style, ref, ...rest
}: AgentTraceProps) {
  const [selected, setSelected] = React.useState<string | null>(null);
  const trackRef = React.useRef<HTMLDivElement>(null);
  const resumeAfterScrub = React.useRef(false);
  const rows = React.useMemo(() => layout(spans), [spans]);
  const total = Math.max(1, duration ?? rows.reduce((max, s) => Math.max(max, s.end), 0));
  const ticks = React.useMemo(() => traceTicks(total), [total]);
  const head = useAgentTracePlayhead({ total, currentTime, live, defaultTime, autoPlay, loop, speed, holdMs, showTokens });
  const registerRow = React.useCallback((index: number, handle: RowHandle | null) => { head.rowsRef.current[index] = handle; }, [head.rowsRef]);
  useTraceLayoutEffect(() => {
    head.rowsRef.current.length = rows.length;
    head.repaint();
  }, [rows, total, currentTime, showTokens, live, selectedSpanId, selected]);

  const selectSpan = (span: LaidSpan) => {
    setSelected(span.id);
    // Footerless traces open details without changing the position in the graph.
    if (showTransport && interactive && (!head.following || !live)) head.seek(span.start);
    onSpanSelect?.(span);
  };
  const scrubFrom = (clientX: number, el: HTMLElement) => {
    const surface = el.dataset.slot === "trace-ruler" ? trackRef.current ?? el : el;
    const inset = Number(surface.dataset.inset ?? 0);
    const rect = surface.getBoundingClientRect();
    const width = rect.width - inset * 2;
    if (width > 0) head.seek(((clientX - rect.left - inset) / width) * total);
  };
  const onScrubDown = (e: React.PointerEvent<HTMLElement>) => {
    resumeAfterScrub.current = replayOnSeek || head.playing;
    head.pause();
    e.currentTarget.setPointerCapture(e.pointerId); scrubFrom(e.clientX, e.currentTarget);
  };
  const onScrubMove = (e: React.PointerEvent<HTMLElement>) => {
    if (e.currentTarget.hasPointerCapture(e.pointerId)) scrubFrom(e.clientX, e.currentTarget);
  };
  const onScrubUp = (e: React.PointerEvent<HTMLElement>) => {
    if (!e.currentTarget.hasPointerCapture(e.pointerId)) return;
    e.currentTarget.releasePointerCapture(e.pointerId);
    if (resumeAfterScrub.current) head.resume();
    resumeAfterScrub.current = false;
  };
  const onScrubCancel = (e: React.PointerEvent<HTMLElement>) => {
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
    resumeAfterScrub.current = false;
  };
  const scrubProps = { onPointerDown: onScrubDown, onPointerMove: onScrubMove, onPointerUp: onScrubUp, onPointerCancel: onScrubCancel };
  const onRailKeyDown = (e: React.KeyboardEvent) => {
    const step = total / 50;
    const delta: Record<string, number> = { ArrowRight: step, ArrowUp: step, ArrowLeft: -step, ArrowDown: -step, PageUp: step * 10, PageDown: -step * 10 };
    if (e.key === "Home") head.seek(0);
    else if (e.key === "End") head.seek(total);
    else if (e.key in delta) head.seek(head.timeRef.current + delta[e.key]);
    else return;
    resumeAfterScrub.current = replayOnSeek || head.playing || resumeAfterScrub.current;
    head.pause();
    e.preventDefault();
  };
  const onRailKeyUp = (e: React.KeyboardEvent) => {
    if (!["Home", "End", "ArrowRight", "ArrowLeft", "ArrowUp", "ArrowDown", "PageUp", "PageDown"].includes(e.key)) return;
    if (resumeAfterScrub.current) head.resume();
    resumeAfterScrub.current = false;
  };
  const trackBox = "absolute left-[calc(var(--gutter)+var(--pad))] right-[calc(var(--meta)+var(--pad))]";
  return (
    <div
      ref={node => { head.rootRef.current = node; if (typeof ref === "function") ref(node); else if (ref) ref.current = node; }}
      data-slot="agent-trace" data-live={live ? "true" : undefined}
      data-playing={head.playing ? "true" : undefined}
      data-following={head.following ? "true" : undefined}
      style={{ ...style, "--label-w": `${labelWidth}px`, "--row": `${rowHeight}px`, "--pad": "0.75rem" } as React.CSSProperties}
      className={cn("group/trace @container/trace bg-card text-card-foreground border-border w-full min-w-0 overflow-hidden rounded-xl border shadow-sm", className)} {...rest}
    >
      <div data-slot="trace-header" className="border-border flex min-w-0 items-center gap-2.5 border-b px-3 py-2.5">
        <span aria-hidden="true" className="bg-muted-foreground/40 group-data-[run=running]/trace:bg-primary group-data-[run=error]/trace:bg-destructive size-1.5 shrink-0 rounded-full" />
        <span className="text-foreground min-w-0 truncate font-mono text-[13px] leading-none font-medium">{runId}</span>
        <span className="text-muted-foreground @sm/trace:inline hidden min-w-0 truncate text-xs">{model ? `${model} · ` : ""}{rows.length} spans</span>
        <span ref={head.statusRef} className="border-border text-muted-foreground ml-auto shrink-0 rounded-full border px-2 py-0.5 font-mono text-[11px] leading-4">{live ? "Running" : "Completed"}</span>
      </div>
      <div className="relative [--gutter:96px] [--meta:3.75rem] @xs/trace:[--gutter:132px] @xs/trace:[--meta:5rem] @md/trace:[--gutter:var(--label-w)] @md/trace:[--meta:9rem]">
        {showRuler && (
          <div data-slot="trace-ruler" {...(interactive ? scrubProps : {})} className={cn("border-border @max-sm/trace:hidden relative h-7 border-b select-none", interactive && "cursor-ew-resize touch-none")}>
            <div className={cn(trackBox, "inset-y-0")}>
              {ticks.map(t => <span key={t} className="text-muted-foreground absolute top-2 -translate-x-1/2 font-mono text-[10px] leading-none tabular-nums" style={{ left: `${t / total * 100}%` }}>{t < 1000 ? `${t}ms` : `${t / 1000}s`}</span>)}
            </div>
          </div>
        )}
        <div className="relative py-1">
          {showRuler && (
            <div aria-hidden="true" className={cn(trackBox, "@max-sm/trace:hidden inset-y-0")}>
              {ticks.map(t => <span key={t} className="bg-border/60 absolute inset-y-0 w-px" style={{ left: `${t / total * 100}%` }} />)}
            </div>
          )}
          <ol data-slot="trace-spans" aria-label={`Spans in ${runId}`} className="relative m-0 list-none p-0">
            {rows.map((span, i) => <li key={span.id}><TraceSpanRow span={span} index={i} total={total} showTokens={showTokens} selected={(selectedSpanId === undefined ? selected : selectedSpanId) === span.id} detailsId={detailsId} onSelect={selectSpan} register={registerRow} /></li>)}
          </ol>
          <div aria-hidden="true" className={cn(trackBox, "pointer-events-none inset-y-0")}>
            <div className="relative h-full w-0" style={{ left: "calc(var(--t,0) * 100%)" }}>
              <span className="bg-primary/70 absolute inset-y-0 w-px" /><span className="bg-primary absolute top-0 size-1.5 -translate-x-[2.5px] rotate-45" />
            </div>
          </div>
          {interactive && <div
            ref={node => { trackRef.current = node; if (!showTransport) head.railRef.current = node; }}
            data-slot="trace-scrub" {...scrubProps}
            role={showTransport ? undefined : "slider"} tabIndex={showTransport ? undefined : 0}
            aria-label={showTransport ? undefined : "Timeline playhead"}
            aria-valuemin={showTransport ? undefined : 0} aria-valuemax={showTransport ? undefined : Math.round(total)}
            aria-valuenow={showTransport ? undefined : Math.round(head.timeRef.current)}
            onKeyDown={onRailKeyDown} onKeyUp={onRailKeyUp}
            className={cn(trackBox, "focus-visible:ring-ring/50 inset-y-0 cursor-ew-resize touch-none rounded-sm outline-none select-none focus-visible:ring-[3px]")}
          />}
        </div>
      </div>
      {showTransport && (
        <div className="border-border flex items-center gap-2 border-t px-3 py-2">
          <button type="button" data-slot="trace-play" onClick={head.togglePlay}
            aria-label={head.following && live ? "Pause live updates" : head.playing ? "Pause replay" : "Play replay"}
            className="bg-primary text-primary-foreground focus-visible:ring-ring/50 relative flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-full border-0 p-0 outline-none focus-visible:ring-[3px] before:absolute before:-inset-1 before:content-['']">
            {head.playing || head.following && live ? <Pause aria-hidden="true" className="size-3.5 fill-current" /> : <Play aria-hidden="true" className="size-3.5 translate-x-px fill-current" />}
          </button>
          <div ref={head.railRef} role="slider" tabIndex={0} aria-label="Playhead" aria-valuemin={0} aria-valuemax={Math.round(total)} aria-valuenow={Math.round(head.timeRef.current)}
            data-inset="6" {...scrubProps} onKeyDown={onRailKeyDown} onKeyUp={onRailKeyUp} className="focus-visible:ring-ring/50 relative h-9 min-w-0 flex-1 cursor-ew-resize touch-none rounded-md outline-none select-none focus-visible:ring-[3px]">
            <div className="bg-foreground/10 absolute inset-x-1.5 top-1/2 h-1 -translate-y-1/2 overflow-hidden rounded-full"><div aria-hidden="true" className="bg-primary h-full w-full origin-left" style={{ transform: "scaleX(var(--t,0))" }} /></div>
            <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 right-1.5 left-1.5"><div className="relative h-full w-0" style={{ left: "calc(var(--t,0) * 100%)" }}><span className="bg-primary border-card absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 shadow-sm" /></div></div>
          </div>
          {live && <button type="button" data-slot="trace-live" onClick={head.followLive} aria-label="Follow live actions" aria-pressed={head.following} className="text-muted-foreground hover:text-primary flex h-9 shrink-0 items-center gap-1 rounded border-0 bg-transparent px-1 py-0 text-[11px] focus-visible:outline-2 focus-visible:outline-primary"><Radio aria-hidden="true" className="size-3" />Live</button>}
          <span ref={head.clockRef} className="text-muted-foreground w-[7rem] shrink-0 text-right font-mono text-[11px] tabular-nums" />
        </div>
      )}
    </div>
  );
}

export default AgentTrace;
