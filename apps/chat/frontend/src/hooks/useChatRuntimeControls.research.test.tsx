/** @vitest-environment happy-dom */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ProviderItem } from "../api/client";
import { RESEARCH_RUNNER_ID } from "../lib/runtimeProfiles";
import { useChatRuntimeControls } from "./useChatRuntimeControls";

const providers: ProviderItem[] = [
  { provider_id: "deepseek", label: "DeepSeek", execution_family: "maverick_agent" },
  { provider_id: "glm", label: "GLM", execution_family: "maverick_agent" },
  { provider_id: "google", label: "Gemini API", execution_family: "maverick_agent" },
  { provider_id: "codex-sol", label: "GPT Sol", execution_family: "native_agent" },
  { provider_id: "codex-astra", label: "GPT Astra", execution_family: "native_agent" },
  { provider_id: "antigravity", label: "Gemini CLI", execution_family: "native_agent" },
].map((provider): ProviderItem => ({
  ...provider,
  description: provider.label,
  default_model_family: provider.provider_id,
  execution_family: provider.execution_family as ProviderItem["execution_family"],
  provider_role: "runtime_engine",
  status: "active",
  selectable: true,
  research_compatible: true,
  workspace_profile_binding_id: `binding-${provider.provider_id}`,
  default_reasoning_effort: "high",
  agentic_effective_tool_handle_mode: "all_currently_authorized",
  agentic_effective_capabilities: {
    status: "active", reason_code: null, snapshot_digest: "fixture",
    execution_mode: "full-access",
    capabilities: {
      streaming: true, tool_orchestration: true, cli: true, mcp: true,
      skill_catalog: true, filesystem_list: true, filesystem_read: true,
      filesystem_write: true, shell: true, interrupt: true, same_turn_steering: false,
      recovery: true, confirmation_resume: true, provider_private_state: true,
      attachment_modalities: [], app_references: true, confirmations: true,
    },
  },
}));

describe("Research model selection", () => {
  let container: HTMLDivElement;
  let root: Root;
  let controls: ReturnType<typeof useChatRuntimeControls>;
  const setActiveProviderId = vi.fn();
  const setSelectedAgentTypeId = vi.fn();
  const setComposerError = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  async function render(providerId: string, agentTypeId = RESEARCH_RUNNER_ID) {
    function Harness() {
      controls = useChatRuntimeControls({
        activeThread: null, activeSession: null, activeTurn: null,
        activeProviderId: providerId, agentCatalogAppId: "agents",
        canStopTurn: false, providers, selectedAgentTypeId: agentTypeId,
        executionMode: "full-access", workspaceId: "default",
        setActiveProviderId, setSelectedAgentTypeId, setComposerError,
        setActiveTurn: vi.fn(), setError: vi.fn(), setEvents: vi.fn(),
      });
      return null;
    }
    await act(async () => root.render(<Harness />));
  }

  it.each(providers)("keeps $label when Research is activated", async (provider) => {
    await render(provider.provider_id, "");
    await act(async () => controls.handleSelectAgent(RESEARCH_RUNNER_ID));
    expect(setSelectedAgentTypeId).toHaveBeenCalledWith(RESEARCH_RUNNER_ID);
    expect(setActiveProviderId).not.toHaveBeenCalled();
    await render(provider.provider_id);
    expect(await controls.selectedAgentRuntimeConfig(null)).toMatchObject({
      runtime_profile: "research",
      workspace_profile_binding_id: provider.workspace_profile_binding_id,
      reasoning_effort: "high", system_prompt: "", skill_ids: [],
    });
  });

  it.each(providers)("switches from DeepSeek to $label and clears a previous error", async (provider) => {
    await render("deepseek");
    await act(async () => controls.handleSelectProvider(provider.provider_id, "high"));
    expect(setActiveProviderId).toHaveBeenCalledWith(provider.provider_id);
    expect(setComposerError).toHaveBeenLastCalledWith(null);
    expect(setSelectedAgentTypeId).not.toHaveBeenCalled();
  });
});
