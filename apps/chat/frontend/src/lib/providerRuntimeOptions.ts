import type {
  AgenticProfileItem,
  HostedTextProviderStatus,
  ProviderItem,
  ProviderPayload,
  ProviderReasoningOption,
} from "../api/client";
import type { AgentRuntimeConfig } from "../hooks/useMessageSubmission";
import {
  EXECUTION_FAMILY_CATALOG,
  NO_WORKSPACE_ACTIONS_MESSAGE,
} from "./executionFamilies";

export function providerItemsFromPayload(payload: ProviderPayload): ProviderItem[] {
  const options: ProviderItem[] = [];
  const familyCatalog = new Map(
    (payload.execution_families?.length
      ? payload.execution_families
      : EXECUTION_FAMILY_CATALOG
    ).map((family, index) => [family.family_id, { ...family, index }]),
  );
  const agenticProfiles = (payload.agentic_profiles?.items || []).filter(
    (profile) =>
      profile.selectable === true &&
      (profile.execution_family === "native_agent" || profile.execution_family === "maverick_agent") &&
      profile.family_contract_status === "complete" &&
      profile.full_workspace_status === "certified" &&
      nativeProfileRuntimeReady(payload, profile) &&
      profile.containment_status !== "NO-GO" &&
      profile.enabled &&
      profile.certified === true &&
      profile.effective_capabilities?.status === "active" &&
      (profile.rollout_status === "preview" || profile.rollout_status === "available") &&
      profile.certificate?.effective_status === "active",
  );
  if (agenticProfiles.length) {
    options.push(
      ...agenticProfiles.map((profile) => {
        const engine = [payload.active_provider, ...(payload.available_providers || [])].find(
          (provider) => provider?.provider_id === profile.runtime_engine_id,
        );
        const modelProvider = providerForAgenticProfile(payload, profile);
        const model = modelProvider?.model_options?.find((candidate) => candidate.model_id === profile.model_id);
        const reasoning = reasoningForAgenticProfile(payload, profile);
        return decorateExecutionFamily({
          ...(engine || {
            description: "Pinned agentic runtime profile",
            label: model?.label || profile.model_id,
            status: "active",
            default_model_family: profile.model_id,
          }),
          provider_id: profile.is_default
            ? profile.runtime_engine_id
            : `agentic:${encodeURIComponent(profile.workspace_profile_binding_id)}`,
          provider_role: "runtime_engine",
          workspace_profile_binding_id: profile.workspace_profile_binding_id,
          default_model_family: profile.model_id,
          label: profile.runtime_engine_id === "codex"
            ? model?.label || profile.model_id
            : profile.display_name,
          description: modelProvider?.label || profile.model_provider_id,
          status: "active",
          agentic_rollout_status: profile.rollout_status,
          agentic_certificate_status: profile.certificate?.effective_status || null,
          agentic_certificate_expires_at: profile.certificate?.expires_at || null,
          agentic_egress_policy_id: profile.egress_policy_id || null,
          agentic_allowed_tool_handles: profile.allowed_tool_handles || [],
          agentic_max_estimated_cost_microusd: profile.max_estimated_cost_microusd ?? null,
          agentic_containment_status: profile.containment_status,
          agentic_containment_reason: profile.containment_reason || null,
          agentic_data_destination: profile.data_destination || null,
          agentic_egress_policy: profile.egress_policy || null,
          agentic_data_policy: profile.data_policy || null,
          agentic_effective_capabilities: profile.effective_capabilities || null,
          execution_family: profile.execution_family || undefined,
          selectable: true,
          unavailable_reason: null,
          full_workspace_status: profile.full_workspace_status,
          full_workspace_contract_revision: profile.full_workspace_contract_revision || null,
          harness_recipe: profile.harness_recipe || null,
          provider_detail: agenticProviderDetail(profile),
          profile_detail: agenticProfileDetail(profile),
          legacy_selection_ids: [profile.workspace_profile_binding_id],
          capabilities: {
            ...(engine?.capabilities || {}),
            supports_skills: profile.effective_capabilities?.capabilities.skill_catalog === true,
          },
          input_modalities: profile.effective_capabilities?.capabilities.attachment_modalities || [],
          default_reasoning_effort: reasoning.defaultEffort,
          supported_reasoning_efforts: reasoning.options,
        }, profile.execution_family!, familyCatalog);
      }),
    );
  } else if (
    (!payload.agentic_profiles || !(payload.agentic_profiles.items || []).length)
    && payload.active_provider
    && providerIsActive(payload.active_provider)
  ) {
    const fallbackFamily = payload.active_provider.provider_id === "codex"
      && payload.active_provider.provider_role === "runtime_engine"
      && payload.active_provider.kind === "runtime_backend"
      ? "native_agent"
      : null;
    const nativeRuntime = payload.native_agents?.items.find(
      (item) => item.runtime_engine_id === payload.active_provider?.provider_id,
    );
    if (fallbackFamily && (!payload.native_agents || nativeRuntime?.selectable === true)) {
      options.push(decorateExecutionFamily(
        { ...payload.active_provider, execution_family: fallbackFamily, selectable: true },
        fallbackFamily,
        familyCatalog,
      ));
    }
  }

  const hostedProviders = hostedTextProviders(payload.hosted_text);
  if (hostedProviders.length) {
    options.push(...hostedProviders.flatMap((provider) =>
      hostedModelProviderItems(payload.hosted_text, provider).map((item) =>
        decorateExecutionFamily(item, "hosted_text", familyCatalog),
      ),
    ));
  }

  if (
    !options.length
    && !payload.execution_families?.length
    && !payload.agentic_profiles
    && !payload.hosted_text
  ) {
    options.push(...(payload.items || payload.available_providers || []).filter(providerIsSelectable));
  }

  return applySelectionMigrationAliases(
    dedupeProviders(options),
    payload.selection_migration?.records || [],
  );
}

function nativeProfileRuntimeReady(payload: ProviderPayload, profile: AgenticProfileItem): boolean {
  if (profile.execution_family !== "native_agent" || !payload.native_agents) {
    return true;
  }
  return payload.native_agents.items.some(
    (item) => item.runtime_engine_id === profile.runtime_engine_id && item.selectable,
  );
}

function decorateExecutionFamily(
  provider: ProviderItem,
  familyId: "native_agent" | "maverick_agent" | "hosted_text",
  catalog: Map<string, { label: string; description: string; index: number }>,
): ProviderItem {
  const family = catalog.get(familyId);
  return {
    ...provider,
    execution_family: familyId,
    execution_family_label: family?.label,
    execution_family_description: family?.description,
    execution_family_order: family?.index,
  };
}

function agenticProviderDetail(profile: AgenticProfileItem): string {
  const destination = profile.data_destination?.display_label || profile.model_provider_id;
  return `Provider: ${profile.model_provider_id} · Destination: ${destination}`;
}

function agenticProfileDetail(profile: AgenticProfileItem): string {
  const recipe = profile.harness_recipe?.id
    ? `${profile.harness_recipe.id}@${profile.harness_recipe.revision || "unversioned"}`
    : "unavailable";
  return `Profile: ${profile.definition_id}@${profile.definition_revision} · Recipe: ${recipe} · Full Workspace: ${profile.full_workspace_contract_revision || "unavailable"}`;
}

function reasoningForAgenticProfile(
  _payload: ProviderPayload,
  profile: AgenticProfileItem,
): { defaultEffort: string | null; options: ProviderReasoningOption[] } {
  const options = profile.supported_reasoning_efforts || [];
  const requestedDefault = profile.default_reasoning_effort || null;
  const defaultEffort = options.length && !options.some((option) => option.effort === requestedDefault)
    ? options[0]?.effort || null
    : requestedDefault;
  return { defaultEffort, options };
}

function providerForAgenticProfile(
  payload: ProviderPayload,
  profile: AgenticProfileItem,
): ProviderItem | undefined {
  return [
    payload.active_provider,
    ...(payload.available_providers || []),
    ...(payload.items || []),
    payload.hosted_text?.active_provider,
    ...(payload.hosted_text?.available_providers || []),
  ].find((candidate) => candidate?.provider_id === profile.model_provider_id) || undefined;
}

export function providerUsesPlainHostedRuntime(provider: ProviderItem | null | undefined): boolean {
  return provider?.provider_role === "model_provider" && provider.kind === "hosted_api";
}

export function hostedProviderRuntimeConfig(provider: ProviderItem | null | undefined): AgentRuntimeConfig | null {
  if (!providerUsesPlainHostedRuntime(provider)) {
    return null;
  }
  if (!provider) {
    return null;
  }
  return {
    agent_id: "chat",
    agent_role_id: "",
    agent_type_id: "",
    runtime_mode: "plain_hosted_chat",
    routing_profile: "fast_model",
    hosted_provider_id: provider.hosted_provider_id || provider.provider_id,
    hosted_model_id: provider.hosted_model_id || provider.default_model_family || "",
    skill_catalog_app_id: "",
    skill_ids: [],
    skill_activation_mode: "explicit",
    source_app_id: "chat",
    system_prompt: "",
    title: provider?.label || "Text-only model",
  };
}

function hostedTextProviders(status: HostedTextProviderStatus | null | undefined): ProviderItem[] {
  const providers = [
    status?.active_provider,
    ...(status?.available_providers || []),
  ].filter((provider): provider is ProviderItem => Boolean(provider) && providerIsSelectable(provider as ProviderItem));
  return dedupeProviders(providers);
}

function hostedModelProviderItems(status: HostedTextProviderStatus | null | undefined, provider: ProviderItem): ProviderItem[] {
  const activeProviderId = status?.active_provider?.provider_id || "";
  const selectedModelId =
    activeProviderId === provider.provider_id
      ? status?.model_settings?.selected_model_id || provider.default_model_family || ""
      : provider.default_model_family || "";
  const models =
    activeProviderId === provider.provider_id && status?.model_settings?.available_models?.length
      ? status.model_settings.available_models
      : provider.model_options || [];
  const textModels = models.filter(modelSupportsPlainHostedChat);
  if (models.length && !textModels.length) {
    return [];
  }
  const sortedModels = [...textModels].sort((left, right) => {
    if (left.model_id === selectedModelId) {
      return -1;
    }
    if (right.model_id === selectedModelId) {
      return 1;
    }
    return left.label.localeCompare(right.label);
  });
  if (!sortedModels.length) {
    const profile = hostedTextProfile(status, provider.provider_id, selectedModelId || provider.default_model_family || "");
    const profileMissing = Boolean(status?.profiles && !profile);
    return [
      {
        ...provider,
        provider_id: hostedRuntimeOptionId(provider.provider_id, selectedModelId || provider.default_model_family || "default"),
        hosted_provider_id: provider.provider_id,
        hosted_model_id: selectedModelId || provider.default_model_family || "",
        label: selectedModelId || "Hosted model",
        description: provider.label || provider.provider_id,
        execution_family: "hosted_text",
        selectable: profile?.selectable ?? !profileMissing,
        unavailable_reason: profile?.unavailable_reason || (profileMissing ? "hosted_text_profile_missing" : null),
        hosted_text_profile: profile,
        provider_detail: `Provider: ${provider.label || provider.provider_id}`,
        profile_detail: NO_WORKSPACE_ACTIONS_MESSAGE,
        legacy_selection_ids: [`fast_model:${provider.provider_id}:${encodeURIComponent(selectedModelId)}`],
      },
    ];
  }
  return sortedModels.map((model) => {
    const profile = hostedTextProfile(status, provider.provider_id, model.model_id);
    const profileMissing = Boolean(status?.profiles && !profile);
    return {
      ...provider,
      provider_id: hostedRuntimeOptionId(provider.provider_id, model.model_id),
      hosted_provider_id: provider.provider_id,
      hosted_model_id: model.model_id,
      default_model_family: model.model_id,
      label: model.label || model.model_id,
      description: provider.label || provider.provider_id,
      input_modalities: model.input_modalities || [],
      output_modalities: model.output_modalities || [],
      execution_family: "hosted_text" as const,
      selectable: profile?.selectable ?? !profileMissing,
      unavailable_reason: profile?.unavailable_reason || (profileMissing ? "hosted_text_profile_missing" : null),
      hosted_text_profile: profile,
      provider_detail: `Provider: ${provider.label || provider.provider_id}`,
      profile_detail: NO_WORKSPACE_ACTIONS_MESSAGE,
      legacy_selection_ids: [`fast_model:${provider.provider_id}:${encodeURIComponent(model.model_id)}`],
    };
  });
}

function hostedTextProfile(
  status: HostedTextProviderStatus | null | undefined,
  providerId: string,
  modelId: string,
) {
  return (status?.profiles || []).find(
    (item) => item.profile.provider_id === providerId && item.profile.model_id === modelId,
  ) || null;
}

function modelSupportsPlainHostedChat(model: { output_modalities?: string[] | null }): boolean {
  const outputs = model.output_modalities || [];
  return !outputs.length || outputs.includes("text");
}

function hostedRuntimeOptionId(providerId: string, modelId: string): string {
  return `hosted:${providerId}:${encodeURIComponent(modelId)}`;
}

function providerIsActive(provider: ProviderItem): boolean {
  return provider.status === "active";
}

function providerIsSelectable(provider: ProviderItem): boolean {
  return provider.selectable !== false
    && providerIsActive(provider)
    && (provider.provider_role === "runtime_engine" || providerUsesPlainHostedRuntime(provider));
}

function applySelectionMigrationAliases(
  providers: ProviderItem[],
  records: Array<{ source_id: string; canonical_selection_id: string | null }>,
): ProviderItem[] {
  return providers.map((provider) => {
    const aliases = records
      .filter((record) => record.canonical_selection_id === provider.provider_id)
      .map((record) => record.source_id);
    return aliases.length
      ? {
        ...provider,
        legacy_selection_ids: Array.from(new Set([...(provider.legacy_selection_ids || []), ...aliases])),
      }
      : provider;
  });
}

export function migrateLegacyProviderSelectionId(
  selectionId: string,
  providers: ProviderItem[],
): string | null {
  const normalized = selectionId.trim();
  if (!normalized) {
    return null;
  }
  const exact = providers.find((provider) => provider.provider_id === normalized);
  if (exact) {
    return exact.provider_id;
  }
  const aliases = providers.filter((provider) =>
    provider.legacy_selection_ids?.includes(normalized),
  );
  return aliases.length === 1 ? aliases[0].provider_id : null;
}

export function initialProviderSelectionId(
  requestedSelectionId: string | null,
  providers: ProviderItem[],
): string {
  const selectableProviders = providers.filter(providerIsSelectable);
  if (requestedSelectionId !== null) {
    return migrateLegacyProviderSelectionId(requestedSelectionId, selectableProviders) || "";
  }
  return selectableProviders[0]?.provider_id || "";
}

function dedupeProviders(providers: ProviderItem[]): ProviderItem[] {
  const seen = new Set<string>();
  return providers.filter((provider) => {
    if (!provider.provider_id || seen.has(provider.provider_id)) {
      return false;
    }
    seen.add(provider.provider_id);
    return true;
  });
}
