import { useEffect, useState } from "react";
import type { ToolCallMessage } from "../api/client";
import { isLiveTool, toolCallsToTrace } from "../lib/toolTrace";

export function useToolTrace(toolCalls: ToolCallMessage[], createdAt?: string) {
  const live = toolCalls.some(isLiveTool);
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!live) return;
    setNow(Date.now());
    const timer = window.setInterval(() => {
      if (!document.hidden) setNow(Date.now());
    }, 250);
    return () => window.clearInterval(timer);
  }, [live]);
  return toolCallsToTrace(toolCalls, now, createdAt);
}
