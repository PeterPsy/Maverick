import { Dispatch, SetStateAction, useCallback, useEffect, useRef, useState } from "react";
import {
  ChatThread,
  ProviderItem,
  RuntimeEvent,
  RuntimeSession,
  RuntimeTurn,
  getAgentDefinition,
  interruptRuntimeTurn,
  selectProvider,
} from "../api/client";
import { ActiveAppContext, promptWithActiveAppContext } from "../lib/activeAppContext";
import { mergeRuntimeEvents } from "../lib/runtimeEvents";
import type { AgentRuntimeConfig } from "./useMessageSubmission";
import {
  isResearchRunner,
  providerSupportsResearch,
} from "../lib/runtimeProfiles";

type UseChatRuntimeControlsParams = {
  activeThread: ChatThread | null;
  activeSession: RuntimeSession | null;
  activeTurn: RuntimeTurn | null;
  activeProviderId: string;
  agentCatalogAppId: string;
  canStopTurn: boolean;
  providers: ProviderItem[];
  selectedAgentTypeId: string;
  executionMode: "sandbox" | "full-access" | null;
  workspaceId: string;
  setActiveProviderId: (providerId: string) => void;
  setActiveTurn: Dispatch<SetStateAction<RuntimeTurn | null>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setEvents: Dispatch<SetStateAction<RuntimeEvent[]>>;
  setSelectedAgentTypeId: (agentTypeId: string) => void;
  setComposerError: Dispatch<SetStateAction<string | null>>;
};

type CachedAgentRuntimeConfig = Omit<AgentRuntimeConfig, "system_prompt"> & {
  renderedPrompt: string;
};

const agentRuntimeConfigCache = new Map<string, Promise<CachedAgentRuntimeConfig>>();

export function genericAgenticRuntimeConfig(
  provider: ProviderItem | null,
  reasoningEffort: string,
): AgentRuntimeConfig | null {
  if (provider?.provider_role !== "runtime_engine" || !provider.workspace_profile_binding_id) {
    return null;
  }
  return {
    agent_id: "chat",
    agent_role_id: "",
    agent_type_id: "",
    skill_catalog_app_id: "skills",
    skill_ids: [],
    skill_activation_mode: "implicit",
    source_app_id: "chat",
    system_prompt: "",
    title: provider.label || "Chat",
    runtime_mode: "agentic",
    workspace_profile_binding_id: provider.workspace_profile_binding_id,
    reasoning_effort: reasoningEffort || undefined,
  };
}

export function researchRuntimeConfig(
  provider: ProviderItem | null,
  reasoningEffort: string,
): AgentRuntimeConfig | null {
  if (!providerSupportsResearch(provider) || !provider?.workspace_profile_binding_id) {
    return null;
  }
  return {
    agent_id: "research",
    agent_role_id: "",
    agent_type_id: "",
    runtime_mode: "agentic",
    runtime_profile: "research",
    requested_mode: "full-access",
    workspace_profile_binding_id: provider.workspace_profile_binding_id,
    reasoning_effort: reasoningEffort || undefined,
    skill_catalog_app_id: "",
    skill_ids: [],
    skill_activation_mode: "explicit",
    source_app_id: "chat",
    system_prompt: "",
    title: "Research",
  };
}

export function effectiveNewChatReasoningEffort(
  selectedReasoningEffort: string,
  providerDefaultReasoningEffort: string,
): string {
  return selectedReasoningEffort || providerDefaultReasoningEffort;
}

export function clearAgentRuntimeConfigCache(): void {
  agentRuntimeConfigCache.clear();
}

function agentRuntimeConfigCacheKey(workspaceId: string, agentCatalogAppId: string, agentTypeId: string): string {
  return `${workspaceId}:${agentCatalogAppId}:${agentTypeId}`;
}

export function activationModeForAssignedSkills(skillIds: string[]): "implicit" | "explicit" {
  return skillIds.length ? "implicit" : "explicit";
}

function loadAgentRuntimeConfig(workspaceId: string, agentCatalogAppId: string, agentTypeId: string): Promise<CachedAgentRuntimeConfig> {
  const key = agentRuntimeConfigCacheKey(workspaceId, agentCatalogAppId, agentTypeId);
  const cached = agentRuntimeConfigCache.get(key);
  if (cached) {
    return cached;
  }
  const pending = getAgentDefinition(agentCatalogAppId, agentTypeId)
    .then((definitionPayload) => {
      const definition = definitionPayload.agent_definition;
      if (!definitionPayload.exists || !definition) {
        throw new Error("Selected agent is no longer available.");
      }
      const skillIds = definition.skill_ids || [];
      return {
        agent_id: definition.name,
        agent_role_id: "",
        agent_type_id: definition.id,
        renderedPrompt: definition.instructions || "",
        skill_catalog_app_id: "skills",
        skill_ids: skillIds,
        skill_activation_mode: activationModeForAssignedSkills(skillIds),
        source_app_id: agentCatalogAppId,
        title: definition.name,
      };
    })
    .catch((error) => {
      agentRuntimeConfigCache.delete(key);
      throw error;
    });
  agentRuntimeConfigCache.set(key, pending);
  return pending;
}

function preloadAgentRuntimeConfig(workspaceId: string, agentCatalogAppId: string, agentTypeId: string): void {
  if (!workspaceId || !agentCatalogAppId || !agentTypeId) {
    return;
  }
  void loadAgentRuntimeConfig(workspaceId, agentCatalogAppId, agentTypeId).catch(() => undefined);
}

export function useChatRuntimeControls({
  activeThread,
  activeSession,
  activeTurn,
  activeProviderId,
  agentCatalogAppId,
  canStopTurn,
  providers,
  selectedAgentTypeId,
  executionMode,
  workspaceId,
  setActiveProviderId,
  setActiveTurn,
  setError,
  setEvents,
  setSelectedAgentTypeId,
  setComposerError,
}: UseChatRuntimeControlsParams) {
  const activeProvider = providers.find((provider) => provider.provider_id === activeProviderId) || null;
  const researchProvider = providers.find(providerSupportsResearch) || null;
  const researchAvailable = executionMode === "full-access" && researchProvider !== null;
  const [reasoningEffort, setReasoningEffort] = useState("");
  const pendingReasoningEffortRef = useRef("");
  const defaultReasoningEffort = activeProvider?.default_reasoning_effort
    || activeProvider?.supported_reasoning_efforts?.[0]?.effort
    || "";
  const newChatReasoningEffort = effectiveNewChatReasoningEffort(
    reasoningEffort,
    defaultReasoningEffort,
  );
  const pinnedReasoningEffort = activeThread
    ? activeSession?.execution_binding?.reasoning_effort || ""
    : "";

  useEffect(() => {
    if (!isResearchRunner(selectedAgentTypeId)) {
      preloadAgentRuntimeConfig(workspaceId, agentCatalogAppId, selectedAgentTypeId);
    }
  }, [agentCatalogAppId, selectedAgentTypeId, workspaceId]);

  useEffect(() => {
    if (activeThread) {
      if (pinnedReasoningEffort) setReasoningEffort(pinnedReasoningEffort);
      return;
    }
    setReasoningEffort(pendingReasoningEffortRef.current || defaultReasoningEffort);
    pendingReasoningEffortRef.current = "";
  }, [activeProviderId, activeThread, defaultReasoningEffort, pinnedReasoningEffort]);

  async function handleSelectProvider(providerId: string, selectedReasoningEffort = "") {
    if (activeThread) {
      setComposerError("Start a new chat to switch models.");
      return;
    }
    const provider = providers.find((item) => item.provider_id === providerId) || null;
    if (isResearchRunner(selectedAgentTypeId) && !providerSupportsResearch(provider)) {
      setComposerError("Research requires a compatible web-enabled model.");
      return;
    }
    pendingReasoningEffortRef.current = selectedReasoningEffort;
    setReasoningEffort(selectedReasoningEffort);
    setActiveProviderId(providerId);
    if (provider?.provider_role === "runtime_engine") {
      setError(null);
      return;
    }
    try {
      const payload = await selectProvider(providerId);
      setActiveProviderId(payload.active_provider?.provider_id || providerId);
      setError(null);
    } catch (selectError) {
      setError(selectError instanceof Error ? selectError.message : "Unable to select provider.");
    }
  }

  function handleSelectAgent(agentTypeId: string) {
    if (activeThread) {
      return;
    }
    if (isResearchRunner(agentTypeId)) {
      if (!researchAvailable || !researchProvider) {
        setComposerError("Research is available only in a full-access workspace with a compatible model.");
        return;
      }
      if (!providerSupportsResearch(activeProvider)) {
        const effort = researchProvider.default_reasoning_effort
          || researchProvider.supported_reasoning_efforts?.[0]?.effort
          || "";
        pendingReasoningEffortRef.current = effort;
        setReasoningEffort(effort);
        setActiveProviderId(researchProvider.provider_id);
      }
    }
    setSelectedAgentTypeId(agentTypeId);
    setComposerError(null);
    if (!isResearchRunner(agentTypeId)) {
      preloadAgentRuntimeConfig(workspaceId, agentCatalogAppId, agentTypeId);
    }
  }

  const selectedAgentRuntimeConfig = useCallback(async (
    activeApp: ActiveAppContext | null,
  ): Promise<AgentRuntimeConfig | null> => {
    const selectedProvider = providers.find((provider) => provider.provider_id === activeProviderId) || null;
    if (isResearchRunner(selectedAgentTypeId)) {
      const config = researchRuntimeConfig(selectedProvider, newChatReasoningEffort);
      if (!config || executionMode !== "full-access") {
        throw new Error("Research is not available with the selected runtime.");
      }
      return config;
    }
    const genericConfig = genericAgenticRuntimeConfig(selectedProvider, newChatReasoningEffort);
    if (!selectedAgentTypeId || !agentCatalogAppId || !workspaceId) {
      return genericConfig;
    }
    const config = await loadAgentRuntimeConfig(workspaceId, agentCatalogAppId, selectedAgentTypeId);
    return {
      agent_id: config.agent_id,
      agent_role_id: config.agent_role_id,
      agent_type_id: config.agent_type_id,
      skill_catalog_app_id: config.skill_catalog_app_id,
      skill_ids: config.skill_ids,
      skill_activation_mode: config.skill_activation_mode,
      source_app_id: config.source_app_id,
      system_prompt: promptWithActiveAppContext(config.renderedPrompt, activeApp),
      title: config.title,
      runtime_mode: "agentic",
      workspace_profile_binding_id: selectedProvider?.workspace_profile_binding_id,
      reasoning_effort: newChatReasoningEffort || undefined,
    };
  }, [
    activeProviderId,
    agentCatalogAppId,
    executionMode,
    newChatReasoningEffort,
    providers,
    selectedAgentTypeId,
    workspaceId,
  ]);

  async function handleStopTurn() {
    if (!activeTurn || !canStopTurn) {
      return;
    }
    try {
      const response = await interruptRuntimeTurn(activeTurn.turn_id);
      setActiveTurn(response.turn);
      if (response.event) {
        setEvents((current) => mergeRuntimeEvents(current, [response.event as RuntimeEvent]));
      }
      setError(null);
    } catch (stopError) {
      setError(stopError instanceof Error ? stopError.message : "Unable to stop runtime turn.");
    }
  }

  return {
    handleSelectAgent,
    handleSelectProvider,
    handleStopTurn,
    researchAvailable,
    selectedAgentRuntimeConfig,
    reasoningEffort,
    setReasoningEffort,
  };
}
