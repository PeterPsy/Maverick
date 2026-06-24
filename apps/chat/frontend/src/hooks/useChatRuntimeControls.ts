import { Dispatch, SetStateAction, useEffect } from "react";
import {
  ChatThread,
  ProviderItem,
  RuntimeEvent,
  RuntimeTurn,
  getAgentDefinition,
  interruptRuntimeTurn,
  previewAgentPrompt,
  selectProvider,
} from "../api/client";
import { ActiveAppContext, promptWithActiveAppContext } from "../lib/activeAppContext";
import { mergeRuntimeEvents } from "../lib/runtimeEvents";
import { hostedProviderRuntimeConfig, providerUsesPlainHostedRuntime } from "../lib/providerRuntimeOptions";
import type { AgentRuntimeConfig } from "./useMessageSubmission";

type UseChatRuntimeControlsParams = {
  activeThread: ChatThread | null;
  activeTurn: RuntimeTurn | null;
  activeProviderId: string;
  agentCatalogAppId: string;
  canStopTurn: boolean;
  providers: ProviderItem[];
  selectedAgentTypeId: string;
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

export function clearAgentRuntimeConfigCache(): void {
  agentRuntimeConfigCache.clear();
}

function agentRuntimeConfigCacheKey(workspaceId: string, agentCatalogAppId: string, agentTypeId: string): string {
  return `${workspaceId}:${agentCatalogAppId}:${agentTypeId}`;
}

function loadAgentRuntimeConfig(workspaceId: string, agentCatalogAppId: string, agentTypeId: string): Promise<CachedAgentRuntimeConfig> {
  const key = agentRuntimeConfigCacheKey(workspaceId, agentCatalogAppId, agentTypeId);
  const cached = agentRuntimeConfigCache.get(key);
  if (cached) {
    return cached;
  }
  const pending = Promise.all([getAgentDefinition(agentCatalogAppId, agentTypeId), previewAgentPrompt(agentCatalogAppId, agentTypeId)])
    .then(([definitionPayload, promptPayload]) => {
      const definition = definitionPayload.agent_definition;
      if (!definitionPayload.exists || !definition) {
        throw new Error("Selected agent is no longer available.");
      }
      return {
        agent_id: definition.name,
        agent_role_id: definition.role_id,
        agent_type_id: definition.id,
        renderedPrompt: promptPayload.rendered || "",
        skill_catalog_app_id: "skills",
        skill_ids: definition.skill_ids || [],
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
  activeTurn,
  activeProviderId,
  agentCatalogAppId,
  canStopTurn,
  providers,
  selectedAgentTypeId,
  workspaceId,
  setActiveProviderId,
  setActiveTurn,
  setError,
  setEvents,
  setSelectedAgentTypeId,
  setComposerError,
}: UseChatRuntimeControlsParams) {
  useEffect(() => {
    preloadAgentRuntimeConfig(workspaceId, agentCatalogAppId, selectedAgentTypeId);
  }, [agentCatalogAppId, selectedAgentTypeId, workspaceId]);

  async function handleSelectProvider(providerId: string) {
    setActiveProviderId(providerId);
    const provider = providers.find((item) => item.provider_id === providerId) || null;
    if (providerUsesPlainHostedRuntime(provider)) {
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
    setSelectedAgentTypeId(agentTypeId);
    setComposerError(null);
    preloadAgentRuntimeConfig(workspaceId, agentCatalogAppId, agentTypeId);
  }

  async function selectedAgentRuntimeConfig(activeApp: ActiveAppContext | null): Promise<AgentRuntimeConfig | null> {
    const selectedProvider = providers.find((provider) => provider.provider_id === activeProviderId) || null;
    const hostedConfig = hostedProviderRuntimeConfig(selectedProvider);
    if (hostedConfig) {
      return hostedConfig;
    }
    if (!selectedAgentTypeId || !agentCatalogAppId || !workspaceId) {
      return null;
    }
    const config = await loadAgentRuntimeConfig(workspaceId, agentCatalogAppId, selectedAgentTypeId);
    return {
      agent_id: config.agent_id,
      agent_role_id: config.agent_role_id,
      agent_type_id: config.agent_type_id,
      skill_catalog_app_id: config.skill_catalog_app_id,
      skill_ids: config.skill_ids,
      source_app_id: config.source_app_id,
      system_prompt: promptWithActiveAppContext(config.renderedPrompt, activeApp),
      title: config.title,
    };
  }

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
    selectedAgentRuntimeConfig,
  };
}
