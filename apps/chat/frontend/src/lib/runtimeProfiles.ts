import type { ProviderItem } from "../api/client";

export const RESEARCH_RUNNER_ID = "__research__";
export const RESEARCH_TOOL_HANDLES = [
  "mcp:app.browser.web_search",
  "mcp:app.browser.web_open",
] as const;

export function isResearchRunner(agentTypeId: string | null | undefined): boolean {
  return agentTypeId === RESEARCH_RUNNER_ID;
}

export function providerSupportsResearch(provider: ProviderItem | null | undefined): boolean {
  if (
    provider?.provider_role !== "runtime_engine"
    || provider.runtime_engine_id !== "maverick-tool-loop"
    || provider.execution_family !== "maverick_agent"
    || provider.status !== "active"
    || provider.selectable === false
    || provider.full_workspace_status !== "available"
    || provider.agentic_effective_capabilities?.status !== "active"
    || provider.agentic_effective_capabilities.capabilities.tool_orchestration !== true
    || provider.agentic_effective_capabilities.capabilities.mcp !== true
  ) {
    return false;
  }
  if (provider.agentic_effective_tool_handle_mode === "all_currently_authorized") {
    return true;
  }
  const allowed = new Set(provider.agentic_effective_allowed_tool_handles || []);
  return provider.agentic_effective_tool_handle_mode === "exact"
    && RESEARCH_TOOL_HANDLES.every((handle) => allowed.has(handle));
}
