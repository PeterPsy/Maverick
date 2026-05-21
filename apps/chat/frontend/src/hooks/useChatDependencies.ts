import { useCallback, useState } from "react";
import {
  AppDependenciesPayload,
  AgentTypeSummary,
  getAppDependencies,
  getSpeechCapabilities,
  listAgentCatalog,
  listProviders,
  ProviderItem,
  selectedDependencyProviderAppId,
  selectedSharedDependencyProviderAppId,
} from "../api/client";

const AGENT_CATALOG_DEPENDENCY_ALIAS = "agent-catalog";
const AGENT_PROMPT_MATERIALIZER_DEPENDENCY_ALIAS = "agent-prompt-materializer";
const TEXT_TO_SPEECH_DEPENDENCY_ALIAS = "text-to-speech";
const SPEECH_TO_TEXT_DEPENDENCY_ALIAS = "speech-to-text";

function providerItemsFromPayload(payload: Awaited<ReturnType<typeof listProviders>>): ProviderItem[] {
  return payload.items || payload.available_providers || (payload.active_provider ? [payload.active_provider] : []);
}

export function useChatDependencies() {
  const [providers, setProviders] = useState<ProviderItem[]>([]);
  const [activeProviderId, setActiveProviderId] = useState("");
  const [agentCatalogAppId, setAgentCatalogAppId] = useState("");
  const [speechProviderAppId, setSpeechProviderAppId] = useState("");
  const [speechProviderAvailable, setSpeechProviderAvailable] = useState(false);
  const [speechProviderQualityProfile, setSpeechProviderQualityProfile] = useState("");
  const [speechMaxTextChars, setSpeechMaxTextChars] = useState(0);
  const [transcriptionProviderAppId, setTranscriptionProviderAppId] = useState("");
  const [transcriptionProviderAvailable, setTranscriptionProviderAvailable] = useState(false);
  const [transcriptionMaxAudioBytes, setTranscriptionMaxAudioBytes] = useState(0);
  const [transcriptionMaxDurationSeconds, setTranscriptionMaxDurationSeconds] = useState(0);
  const [transcriptionContentTypes, setTranscriptionContentTypes] = useState<string[]>([]);
  const [agentOptions, setAgentOptions] = useState<AgentTypeSummary[]>([]);
  const [selectedAgentTypeId, setSelectedAgentTypeId] = useState("");

  const clearAgentOptions = useCallback(() => {
    setAgentCatalogAppId("");
    setAgentOptions([]);
    setSelectedAgentTypeId("");
  }, []);

  const loadAgentOptionsFromProvider = useCallback(
    async (providerAppId: string) => {
      if (!providerAppId) {
        clearAgentOptions();
        return;
      }
      const catalog = await listAgentCatalog(providerAppId);
      const nextAgentOptions = catalog.agent_types || [];
      setAgentCatalogAppId(providerAppId);
      setAgentOptions(nextAgentOptions);
      setSelectedAgentTypeId((current) => (current && !nextAgentOptions.some((agent) => agent.id === current) ? "" : current));
    },
    [clearAgentOptions],
  );

  const loadAgentOptionsFromDependencies = useCallback(
    async (dependencies: AppDependenciesPayload) => {
      try {
        const providerAppId = selectedSharedDependencyProviderAppId(dependencies, [
          AGENT_CATALOG_DEPENDENCY_ALIAS,
          AGENT_PROMPT_MATERIALIZER_DEPENDENCY_ALIAS,
        ]);
        await loadAgentOptionsFromProvider(providerAppId);
      } catch {
        clearAgentOptions();
      }
    },
    [clearAgentOptions, loadAgentOptionsFromProvider],
  );

  const clearSpeechProvider = useCallback(() => {
    setSpeechProviderAppId("");
    setSpeechProviderAvailable(false);
    setSpeechProviderQualityProfile("");
    setSpeechMaxTextChars(0);
  }, []);

  const loadSpeechProviderFromDependencies = useCallback(
    async (dependencies: AppDependenciesPayload) => {
      try {
        const providerAppId = selectedDependencyProviderAppId(dependencies, TEXT_TO_SPEECH_DEPENDENCY_ALIAS);
        if (!providerAppId) {
          clearSpeechProvider();
          return;
        }
        const capabilities = await getSpeechCapabilities(providerAppId);
        const synthesis = capabilities.interfaces?.["speech.synthesis"];
        if (!synthesis) {
          clearSpeechProvider();
          return;
        }
        const maxTextChars = typeof synthesis.max_text_chars === "number" && synthesis.max_text_chars > 0 ? synthesis.max_text_chars : 0;
        const qualityProfile = typeof synthesis.quality_profile === "string" ? synthesis.quality_profile : "";
        setSpeechProviderAppId(providerAppId);
        setSpeechProviderAvailable(Boolean(synthesis.available && synthesis.provider_available !== false && qualityProfile !== "diagnostic"));
        setSpeechProviderQualityProfile(qualityProfile);
        setSpeechMaxTextChars(maxTextChars);
      } catch {
        clearSpeechProvider();
      }
    },
    [clearSpeechProvider],
  );

  const clearTranscriptionProvider = useCallback(() => {
    setTranscriptionProviderAppId("");
    setTranscriptionProviderAvailable(false);
    setTranscriptionMaxAudioBytes(0);
    setTranscriptionMaxDurationSeconds(0);
    setTranscriptionContentTypes([]);
  }, []);

  const loadTranscriptionProviderFromDependencies = useCallback(
    async (dependencies: AppDependenciesPayload) => {
      try {
        const providerAppId = selectedDependencyProviderAppId(dependencies, SPEECH_TO_TEXT_DEPENDENCY_ALIAS);
        if (!providerAppId) {
          clearTranscriptionProvider();
          return;
        }
        const capabilities = await getSpeechCapabilities(providerAppId);
        const transcription = capabilities.interfaces?.["speech.transcription"];
        if (!transcription) {
          clearTranscriptionProvider();
          return;
        }
        setTranscriptionProviderAppId(providerAppId);
        setTranscriptionProviderAvailable(Boolean(transcription.available && transcription.provider_available !== false));
        setTranscriptionMaxAudioBytes(
          typeof transcription.max_inline_audio_bytes === "number" && transcription.max_inline_audio_bytes > 0
            ? transcription.max_inline_audio_bytes
            : typeof transcription.max_audio_bytes === "number" && transcription.max_audio_bytes > 0
              ? transcription.max_audio_bytes
              : 0,
        );
        setTranscriptionMaxDurationSeconds(
          typeof transcription.max_inline_duration_seconds === "number" && transcription.max_inline_duration_seconds > 0
            ? transcription.max_inline_duration_seconds
            : typeof transcription.max_duration_seconds === "number" && transcription.max_duration_seconds > 0
              ? transcription.max_duration_seconds
              : 0,
        );
        setTranscriptionContentTypes(Array.isArray(transcription.content_types) ? transcription.content_types.filter((item) => typeof item === "string") : []);
      } catch {
        clearTranscriptionProvider();
      }
    },
    [clearTranscriptionProvider],
  );

  const loadAppDependencies = useCallback(async () => {
    try {
      const dependencies = await getAppDependencies("chat");
      await Promise.all([
        loadAgentOptionsFromDependencies(dependencies),
        loadSpeechProviderFromDependencies(dependencies),
        loadTranscriptionProviderFromDependencies(dependencies),
      ]);
    } catch {
      clearAgentOptions();
      clearSpeechProvider();
      clearTranscriptionProvider();
    }
  }, [
    clearAgentOptions,
    clearSpeechProvider,
    clearTranscriptionProvider,
    loadAgentOptionsFromDependencies,
    loadSpeechProviderFromDependencies,
    loadTranscriptionProviderFromDependencies,
  ]);

  const loadInitialChatDependencies = useCallback(async () => {
    const [providerPayload] = await Promise.all([listProviders(), loadAppDependencies()]);
    setProviders(providerItemsFromPayload(providerPayload));
    setActiveProviderId(providerPayload.active_provider?.provider_id || "");
  }, [loadAppDependencies]);

  return {
    activeProviderId,
    agentCatalogAppId,
    agentOptions,
    loadAgentOptionsFromDependencies,
    loadAppDependencies,
    loadInitialChatDependencies,
    providers,
    selectedAgentTypeId,
    setActiveProviderId,
    setSelectedAgentTypeId,
    speechMaxTextChars,
    speechProviderAppId,
    speechProviderAvailable,
    speechProviderQualityProfile,
    transcriptionContentTypes,
    transcriptionMaxAudioBytes,
    transcriptionMaxDurationSeconds,
    transcriptionProviderAppId,
    transcriptionProviderAvailable,
    loadSpeechProviderFromDependencies,
    loadTranscriptionProviderFromDependencies,
  };
}
