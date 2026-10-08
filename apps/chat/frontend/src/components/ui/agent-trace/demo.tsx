"use client";

import { motion, useReducedMotion } from "motion/react";
import { AgentTrace, type TraceSpan } from "@/components/ui/agent-trace";

const RUN: TraceSpan[] = [
  { id: "plan", label: "model.plan", kind: "model", start: 0, end: 740, tokens: 1240, detail: "4 steps" },
  { id: "search", label: "search_docs", kind: "tool", start: 780, end: 1960, detail: "12 matches" },
  { id: "read-session", label: "read_file", kind: "io", start: 1120, end: 1480, status: "cached", detail: "session.ts" },
  { id: "read-token", label: "read_file", kind: "io", start: 1180, end: 1610, detail: "token.ts" },
  { id: "reviewer", label: "agent.reviewer", kind: "agent", start: 2000, end: 5400, tokens: 4820, detail: "2 issues" },
  { id: "grep", label: "grep", kind: "tool", parentId: "reviewer", start: 2060, end: 2340, detail: "9 hits" },
  { id: "review", label: "model.review", kind: "model", parentId: "reviewer", start: 2380, end: 4900, tokens: 3480, detail: "412 lines" },
  { id: "note", label: "write_note", kind: "io", parentId: "reviewer", start: 4940, end: 5320, detail: "notes.md" },
  { id: "tests-1", label: "run_tests", kind: "tool", start: 5460, end: 7180, status: "error", detail: "2 failing" },
  { id: "repair", label: "model.repair", kind: "model", start: 7220, end: 8600, tokens: 2110, detail: "3 edits" },
  { id: "tests-2", label: "run_tests", kind: "tool", start: 8640, end: 9900, attempt: 2, detail: "42 passed" },
  { id: "commit", label: "commit", kind: "io", start: 9940, end: 10400, detail: "3 files" },
];
const TOTAL = 10400;
const settings = {
  speed: 1, autoPlay: false, loop: true, startAt: 0.62, rowHeight: 34, labelWidth: 200,
  showRuler: true, showTransport: true, showTokens: true,
  eyebrow: "Agent observability", headline: "See what the agent actually did.",
  subline: "Twelve spans, one failed test suite, one retry. Drag the timeline to replay the run.",
};

/** Supplied example for component previews; Chat itself always uses runtime data. */
export default function Demo(props: Partial<typeof settings>) {
  const s = { ...settings, ...props };
  const reduce = useReducedMotion();
  const enter = (delay: number) => reduce ? {} : {
    initial: { opacity: 0, y: 14, filter: "blur(6px)" },
    animate: { opacity: 1, y: 0, filter: "blur(0px)" },
    transition: { duration: 0.6, delay, ease: [0.22, 1, 0.36, 1] as const },
  };
  return (
    <div className="bg-background flex min-h-[max(560px,100svh)] w-full flex-col items-center justify-center px-5 py-16 sm:px-8">
      <div className="flex w-full max-w-4xl flex-col items-center">
        <motion.p {...enter(0)} className="text-muted-foreground border-border mb-5 inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium">
          <span aria-hidden="true" className="bg-primary size-1.5 rounded-full" />{s.eyebrow}
        </motion.p>
        <motion.h1 {...enter(0.08)} className="text-foreground text-center text-4xl font-semibold tracking-tight text-balance sm:text-5xl">{s.headline}</motion.h1>
        <motion.p {...enter(0.16)} className="text-muted-foreground mt-4 max-w-2xl text-center text-sm text-balance sm:text-base">{s.subline}</motion.p>
        <motion.div {...enter(0.24)} className="mt-10 w-full">
          <AgentTrace id="agent-trace-demo" spans={RUN} duration={TOTAL} runId="run_7c41f2" model="claude-opus-5"
            defaultTime={s.startAt * TOTAL} autoPlay={s.autoPlay} loop={s.loop} speed={s.speed}
            rowHeight={s.rowHeight} labelWidth={s.labelWidth} showRuler={s.showRuler} showTransport={s.showTransport} showTokens={s.showTokens} />
        </motion.div>
      </div>
    </div>
  );
}
