import type { ToolCallMessage } from "../api/client";
import type { TraceSpan } from "../components/ui/agent-trace";
import { toolActivityLabel } from "./toolPresentation";

export const toolTraceKey = (tool: ToolCallMessage, index: number) => tool.id || `${tool.name}-${index}`;
export const isLiveTool = (tool: ToolCallMessage) => tool.status === "started" || tool.status === "updated" || tool.status === "awaiting_confirmation";
const timestamp = (value?: string) => value && Number.isFinite(Date.parse(value)) ? Date.parse(value) : undefined;

/** Project existing display events only; never infer tokens, retries or cache hits. */
export function toolCallsToTrace(tools: ToolCallMessage[], now: number, createdAt?: string) {
  const starts = tools.map(tool => timestamp(tool.startedAt) ?? timestamp(tool.createdAt));
  const origin = Math.min(...starts.filter((time): time is number => time != null), timestamp(createdAt) ?? Infinity);
  const base = Number.isFinite(origin) ? origin : now;
  const ids = new Map<string, string>();
  tools.forEach((tool, index) => {
    for (const key of ["invocation_id", "tool_call_id", "provider_tool_call_id", "call_id", "item_id"]) {
      if (typeof tool.detail[key] === "string") ids.set(tool.detail[key], toolTraceKey(tool, index));
    }
  });
  const spans: TraceSpan[] = tools.map((tool, index) => {
    const active = isLiveTool(tool);
    const start = Math.max(0, (starts[index] ?? base) - base);
    const end = Math.max(start, (active ? now : timestamp(tool.endedAt) ?? timestamp(tool.createdAt) ?? base) - base);
    const parent = tool.detail.parent_tool_call_id ?? tool.detail.parent_invocation_id;
    const result = typeof tool.detail.summary === "string" ? tool.detail.summary
      : typeof tool.detail.exit_code === "number" ? `Exit ${tool.detail.exit_code}`
      : Array.isArray(tool.detail.results) ? `${tool.detail.results.length} results`
      : Array.isArray(tool.detail.changes) ? `${tool.detail.changes.length} files`
      : tool.status === "failed" ? "Failed" : "Completed";
    return {
      id: toolTraceKey(tool, index), label: toolActivityLabel(tool), start, end,
      status: tool.status === "failed" ? "error" : tool.status === "awaiting_confirmation" ? "waiting"
        : active ? "running" : tool.detail.cached === true ? "cached" : "ok",
      kind: tool.detail.tool_kind === "file_change" ? "io" : "tool",
      parentId: typeof parent === "string" ? ids.get(parent) : undefined,
      detail: result.replace(/\s+/g, " ").slice(0, 80),
      tokens: typeof tool.detail.tokens === "number" && tool.detail.tokens >= 0 ? tool.detail.tokens : undefined,
      attempt: typeof tool.detail.attempt === "number" ? tool.detail.attempt : undefined,
    };
  });
  const live = tools.some(isLiveTool);
  const duration = Math.max(1, ...spans.map(span => span.end));
  return { spans, duration, live };
}
