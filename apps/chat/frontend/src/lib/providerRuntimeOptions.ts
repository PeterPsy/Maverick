import type {
  AgenticProfileItem,
  ProviderItem,
  ProviderPayload,
  ProviderReasoningOption,
} from "../api/client";
import { EXECUTION_FAMILY_CATALOG } from "./executionFamilies";

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
        (!profile.runtime_status || profile.runtime_status === "complete") &&
        nativeProfileRuntimeReady(payload, profile) &&
        profile.containment_status !== "NO-GO" &&
        profile.enabled &&
        profile.effective_capabilities?.status === "active",
    );
  if (agenticProfiles.length) {
    options.push(
      ...agenticProfiles.map((profile) => {
        const engine = [payload.active_provider, ...(payload.available_providers || [])].find(
          (provider) => provider?.provider_id === profile.runtime_engine_id,
        );
        const modelProvider = providerForAgenticProfile(payload, profile);
        const model = engine?.model_options?.find((candidate) => candidate.model_id === profile.model_id)
          || modelProvider?.model_options?.find((candidate) => candidate.model_id === profile.model_id);
        const reasoning = reasoningForAgenticProfile(payload, profile);
        const isDefault = profile.is_default
          || profile.workspace_profile_binding_id === payload.agentic_profiles?.default_binding_id;
        return decorateExecutionFamily({
          ...(engine || {
            description: "Pinned agentic runtime profile",
            label: model?.label || profile.model_id,
            status: "active",
            default_model_family: profile.model_id,
          }),
          provider_id: isDefault
            ? profile.runtime_engine_id
            : `agentic:${encodeURIComponent(profile.workspace_profile_binding_id)}`,
          provider_role: "runtime_engine",
          runtime_engine_id: profile.runtime_engine_id,
          workspace_profile_binding_id: profile.workspace_profile_binding_id,
          default_model_family: profile.model_id,
          label: model?.label || profile.display_name.split(" · ")[0]?.trim() || profile.model_id,
          description: modelProvider?.label || profile.model_provider_id,
          status: "active",
          agentic_egress_policy_id: profile.egress_policy_id || null,
          agentic_allowed_tool_handles: profile.allowed_tool_handles || [],
          agentic_tool_handle_mode: profile.tool_handle_mode,
          agentic_effective_allowed_tool_handles: profile.effective_allowed_tool_handles || [],
          agentic_effective_tool_handle_mode: profile.effective_tool_handle_mode,
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
          research_compatible: profile.research_compatible === true,
          provider_detail: agenticProviderDetail(profile),
          profile_detail: agenticProfileDetail(profile),
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

  if (
    !options.length
    && !payload.execution_families?.length
    && !payload.agentic_profiles
  ) {
    options.push(...(payload.items || payload.available_providers || []).filter(providerIsSelectable));
  }

  return dedupeProviders(options);
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
  familyId: "native_agent" | "maverick_agent",
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
  return `Runtime: ${profile.runtime_engine_id} · Model: ${profile.model_provider_id}/${profile.model_id}`;
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

function providerIsActive(provider: ProviderItem): boolean {
  return provider.status === "active";
}

function providerIsSelectable(provider: ProviderItem): boolean {
  return provider.selectable !== false
    && providerIsActive(provider)
    && provider.provider_role === "runtime_engine";
}

export function initialProviderSelectionId(
  requestedSelectionId: string | null,
  providers: ProviderItem[],
): string {
  const selectableProviders = providers.filter(providerIsSelectable);
  if (requestedSelectionId !== null) {
    return selectableProviders.some(
      (provider) => provider.provider_id === requestedSelectionId,
    ) ? requestedSelectionId : "";
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
