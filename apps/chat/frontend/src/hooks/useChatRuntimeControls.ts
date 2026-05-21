import { Dispatch, SetStateAction } from "react";
import {
  ChatThread,
  RuntimeEvent,
  RuntimeTurn,
  getAgentDefinition,
  interruptRuntimeTurn,
  previewAgentPrompt,
  selectProvider,
} from "../api/client";
import { ActiveAppContext, promptWithActiveAppContext } from "../lib/activeAppContext";
import { mergeRuntimeEvents } from "../lib/runtimeEvents";
import type { AgentRuntimeConfig } from "./useMessageSubmission";

type UseChatRuntimeControlsParams = {
  activeThread: ChatThread | null;
  activeTurn: RuntimeTurn | null;
  agentCatalogAppId: string;
  canStopTurn: boolean;
  selectedAgentTypeId: string;
  setActiveProviderId: (providerId: string) => void;
  setActiveTurn: Dispatch<SetStateAction<RuntimeTurn | null>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setEvents: Dispatch<SetStateAction<RuntimeEvent[]>>;
  setSelectedAgentTypeId: (agentTypeId: string) => void;
  setComposerError: Dispatch<SetStateAction<string | null>>;
};

export function useChatRuntimeControls({
  activeThread,
  activeTurn,
  agentCatalogAppId,
  canStopTurn,
  selectedAgentTypeId,
  setActiveProviderId,
  setActiveTurn,
  setError,
  setEvents,
  setSelectedAgentTypeId,
  setComposerError,
}: UseChatRuntimeControlsParams) {
  async function handleSelectProvider(providerId: string) {
    setActiveProviderId(providerId);
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
  }

  async function selectedAgentRuntimeConfig(activeApp: ActiveAppContext | null): Promise<AgentRuntimeConfig | null> {
    if (!selectedAgentTypeId || !agentCatalogAppId) {
      return null;
    }
    const [definitionPayload, promptPayload] = await Promise.all([
      getAgentDefinition(agentCatalogAppId, selectedAgentTypeId),
      previewAgentPrompt(agentCatalogAppId, selectedAgentTypeId),
    ]);
    const definition = definitionPayload.agent_definition;
    if (!definitionPayload.exists || !definition) {
      throw new Error("Selected agent is no longer available.");
    }
    return {
      agent_id: definition.name,
      agent_role_id: definition.role_id,
      agent_type_id: definition.id,
      skill_ids: definition.skill_ids || [],
      source_app_id: agentCatalogAppId,
      system_prompt: promptWithActiveAppContext(promptPayload.rendered || "", activeApp),
      title: definition.name,
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
