import type { ChatThread, ProviderItem, RuntimeSession } from "../api/client";
import { providerUsesPlainHostedRuntime } from "./providerRuntimeOptions";

export type ComposerRuntimeCapabilities = {
  allowedAttachmentInputModalities: string[] | null;
  appReferencesAllowed: boolean;
};

export function composerRuntimeCapabilities({
  activeSession,
  activeThread,
  selectedProvider,
}: {
  activeSession: RuntimeSession | null;
  activeThread: ChatThread | null;
  selectedProvider: ProviderItem | null;
}): ComposerRuntimeCapabilities {
  if (isPlainHostedComposer({ activeSession, activeThread, selectedProvider })) {
    return {
      allowedAttachmentInputModalities: selectedProvider?.input_modalities || [],
      appReferencesAllowed: false,
    };
  }

  if (selectedProvider?.provider_role !== "runtime_engine") {
    return {
      allowedAttachmentInputModalities: null,
      appReferencesAllowed: false,
    };
  }

  if (isContainedAgenticComposer(activeSession, selectedProvider)) {
    return {
      allowedAttachmentInputModalities: [],
      appReferencesAllowed: false,
    };
  }

  const effective = (
    activeThread ? activeSession?.agentic_governance?.effective_capabilities : null
  ) ?? selectedProvider.agentic_effective_capabilities;
  if (effective) {
    const active = effective.status === "active";
    return {
      allowedAttachmentInputModalities: active
        ? [...(effective.capabilities.attachment_modalities || [])]
        : [],
      appReferencesAllowed: active && effective.capabilities.app_references === true,
    };
  }

  if (isUnprojectedLocalCodexComposer({ activeSession, activeThread, selectedProvider })) {
    // Exact local Codex predates the effective-capability projection. Preserve
    // its existing local attachment/reference behavior during a rolling
    // frontend/backend update; unknown or hosted runtimes still fail closed.
    return {
      allowedAttachmentInputModalities: null,
      appReferencesAllowed: true,
    };
  }

  return {
    allowedAttachmentInputModalities: [],
    appReferencesAllowed: false,
  };
}

function isUnprojectedLocalCodexComposer({
  activeSession,
  activeThread,
  selectedProvider,
}: {
  activeSession: RuntimeSession | null;
  activeThread: ChatThread | null;
  selectedProvider: ProviderItem;
}): boolean {
  return hasExactLocalCodexSessionIdentity(activeSession, activeThread)
    && selectedProvider.provider_id === "codex"
    && selectedProvider.status === "active"
    && selectedProvider.agentic_containment_status !== "NO-GO"
    && activeSession?.agentic_containment?.status !== "NO-GO"
    && !selectedProvider.workspace_profile_binding_id
    && runtimeEngineId({ activeSession, activeThread, selectedProvider }) === "codex";
}

function hasExactLocalCodexSessionIdentity(
  activeSession: RuntimeSession | null,
  activeThread: ChatThread | null,
): boolean {
  const binding = activeSession?.execution_binding;
  if (!binding) {
    return !activeThread || activeSession?.provider_id === "codex";
  }
  return binding.runtime_engine_id === "codex"
    && binding.adapter_id === "codex-app-server"
    && binding.model_provider_id === "codex"
    && binding.provider_protocol === "codex-app-server-stdio";
}

function isContainedAgenticComposer(
  activeSession: RuntimeSession | null,
  selectedProvider: ProviderItem,
): boolean {
  return selectedProvider.status === "contained"
    || selectedProvider.agentic_containment_status === "NO-GO"
    || activeSession?.agentic_containment?.status === "NO-GO"
    || activeSession?.agentic_governance?.containment.status === "NO-GO";
}

function isPlainHostedComposer({
  activeSession,
  activeThread,
  selectedProvider,
}: {
  activeSession: RuntimeSession | null;
  activeThread: ChatThread | null;
  selectedProvider: ProviderItem | null;
}): boolean {
  const persistedMode = activeSession?.runtime_mode || activeThread?.runtime_mode || "";
  if (persistedMode) {
    return persistedMode === "plain_hosted_chat";
  }
  return providerUsesPlainHostedRuntime(selectedProvider);
}

function runtimeEngineId({
  activeSession,
  activeThread,
  selectedProvider,
}: {
  activeSession: RuntimeSession | null;
  activeThread: ChatThread | null;
  selectedProvider: ProviderItem;
}): string {
  if (!activeThread) {
    return selectedProvider.provider_id;
  }
  return activeSession?.execution_binding?.runtime_engine_id
    || activeSession?.provider_id
    || activeThread.provider_id
    || selectedProvider.provider_id;
}
