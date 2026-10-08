"use client";

import * as React from "react";
import { Bot, CircleAlert, Cpu, FileText, Hourglass, Wrench, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatMs, metaText, rowState, statusWord, type LaidSpan, type RowHandle } from "./agent-trace-model";

const KIND_ICON = { agent: Bot, model: Cpu, tool: Wrench, io: FileText } as const;

interface TraceSpanRowProps {
  span: LaidSpan;
  index: number;
  total: number;
  showTokens: boolean;
  selected: boolean;
  detailsId?: string;
  onSelect: (span: LaidSpan) => void;
  register: (index: number, handle: RowHandle | null) => void;
}

export const TraceSpanRow = React.memo(function TraceSpanRow({
  span, index, total, showTokens, selected, detailsId, onSelect, register,
}: TraceSpanRowProps) {
  const Icon = KIND_ICON[span.kind ?? "tool"];
  const accent = span.kind === "agent" || span.kind === "model";
  const settled = rowState(span, total);
  return (
    <div
      ref={node => register(index, node ? {
        el: node, span,
        meta: node.querySelector("[data-part='meta']"),
        dur: node.querySelector("[data-part='dur']"),
        status: node.querySelector("[data-part='status']"),
      } : null)}
      data-slot="trace-span" data-span-id={span.id} data-state={settled}
      data-selected={selected ? "true" : undefined}
      style={{ "--p": 1 } as React.CSSProperties}
      className="group/row relative flex h-[var(--row)] items-center px-[var(--pad)] transition-colors duration-150 data-[selected=true]:bg-muted/40 data-[state=running]:bg-muted/60"
    >
      {span.depth > 0 && (
        <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 left-[var(--pad)]">
          {Array.from({ length: span.depth }, (_, d) => (
            <span key={d} className="bg-border absolute inset-y-0 w-px" style={{ left: `${d * 12 + 11}px` }} />
          ))}
        </div>
      )}
      <span data-part="status" className="sr-only">{statusWord(span, settled)}</span>
      <button
        type="button" data-slot="trace-span-label" onClick={() => onSelect(span)}
        title={span.label} aria-controls={detailsId} aria-expanded={detailsId ? selected : undefined}
        aria-label={`${span.label}, ${span.kind ?? "tool"}, ${formatMs(span.dur)}${span.attempt && span.attempt > 1 ? `, attempt ${span.attempt}` : ""}`}
        className="hover:bg-muted focus-visible:ring-ring/50 flex h-full w-[var(--gutter)] min-w-0 shrink-0 cursor-pointer items-center gap-1.5 rounded-md border-0 bg-transparent py-0 pr-2 text-left outline-none focus-visible:ring-[3px]"
        style={{ paddingLeft: `${Math.min(span.depth, 6) * 12 + 4}px` }}
      >
        <Icon aria-hidden="true" className={cn(
          "text-muted-foreground size-3.5 shrink-0 transition-colors duration-200",
          accent && "group-data-[state=done]/row:text-primary group-data-[state=running]/row:text-primary",
        )} />
        <span className="text-foreground group-data-[state=queued]/row:text-muted-foreground min-w-0 truncate font-mono text-xs">{span.label}</span>
        {span.attempt != null && span.attempt > 1 && (
          <span className="border-border text-muted-foreground shrink-0 rounded-md border px-1 font-mono text-[10px] leading-4">×{span.attempt}</span>
        )}
      </button>
      <div className="relative h-full min-w-0 flex-1">
        <div className="absolute top-1/2 h-2 min-w-[3px] -translate-y-1/2 overflow-hidden rounded-full"
          style={{ left: `${span.start / total * 100}%`, width: `${span.dur / total * 100}%` }}>
          <span aria-hidden="true" className="bg-foreground/10 absolute inset-0" />
          <span aria-hidden="true" className={cn("absolute inset-0 origin-left",
            span.status === "error" ? "bg-destructive" : accent ? "bg-primary"
              : span.status === "cached" ? "bg-foreground/25" : "bg-foreground/50",
          )} style={{ transform: "scaleX(var(--p,1))" }} />
        </div>
      </div>
      <div className="group-data-[state=queued]/row:opacity-0 flex w-[var(--meta)] shrink-0 items-center justify-end gap-1.5 pl-2">
        {span.status === "error" && <CircleAlert aria-hidden="true" className="text-destructive size-3.5 shrink-0" />}
        {span.status === "cached" && <Zap aria-hidden="true" className="text-muted-foreground size-3 shrink-0" />}
        {span.status === "waiting" && <Hourglass aria-hidden="true" className="text-primary size-3 shrink-0" />}
        <span data-part="meta" className="text-muted-foreground @md/trace:inline hidden min-w-0 truncate font-mono text-[11px] tabular-nums">{metaText(span, 1, showTokens)}</span>
        <span data-part="dur" className={cn("shrink-0 font-mono text-[11px] tabular-nums", span.status === "error" ? "text-destructive" : "text-foreground/70")}>{formatMs(span.dur)}</span>
      </div>
    </div>
  );
});
