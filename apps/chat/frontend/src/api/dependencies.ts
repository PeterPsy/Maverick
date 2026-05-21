import { booleanField, objectField, requestJson, stringArrayField, stringField } from "./http";
import type {
  AgentCatalogPayload,
  AgentDefinitionPayload,
  AgentPromptPreviewPayload,
  AgentTypeSummary,
  AppDependenciesPayload,
  AppEntityReference,
  AppRegistryItem,
  DependencyProviderCandidate,
  DependencyResolutionItem,
  ProviderPayload,
  SearchAppReferencesOptions,
  SkillSummary,
} from "./types";

export function listProviders(): Promise<ProviderPayload> {
  return requestJson<ProviderPayload>("/api/providers");
}

export function selectProvider(provider_id: string): Promise<ProviderPayload> {
  return requestJson<ProviderPayload>("/api/providers/active", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider_id }),
  });
}

export async function listApps(): Promise<AppRegistryItem[]> {
  const payload = await requestJson<{ items?: unknown[] }>("/api/apps");
  return (payload.items || [])
    .map((value) => {
      const item = objectField(value);
      const appId = stringField(item.app_id);
      return {
        app_id: appId,
        name: stringField(item.name, appId || "Unnamed app"),
        description: stringField(item.description),
        status: stringField(item.status, "unknown"),
        frontend_mount: stringField(item.frontend_mount),
        backend_mount: stringField(item.backend_mount),
      };
    })
    .filter((item) => item.app_id && item.status === "enabled");
}

function normalizeDependencyCandidate(value: unknown): DependencyProviderCandidate {
  const item = objectField(value);
  return {
    app_id: stringField(item.app_id),
    name: stringField(item.name),
    version: stringField(item.version),
    interface: stringField(item.interface),
    interface_version: stringField(item.interface_version),
    description: stringField(item.description),
    surfaces: stringArrayField(item.surfaces),
  };
}

function normalizeDependencyResolution(value: unknown): DependencyResolutionItem {
  const item = objectField(value);
  return {
    alias: stringField(item.alias),
    interface: stringField(item.interface),
    version: stringField(item.version),
    required: booleanField(item.required, true),
    cardinality: stringField(item.cardinality, "one"),
    description: stringField(item.description),
    status: stringField(item.status, "unknown"),
    candidates: Array.isArray(item.candidates) ? item.candidates.map(normalizeDependencyCandidate).filter((candidate) => candidate.app_id) : [],
    selected_provider_app_ids: stringArrayField(item.selected_provider_app_ids),
    stale_provider_app_ids: stringArrayField(item.stale_provider_app_ids),
    blocked_reason: item.blocked_reason === null ? null : stringField(item.blocked_reason) || null,
  };
}

export function getAppDependencies(consumerAppId: string): Promise<AppDependenciesPayload> {
  const params = new URLSearchParams({ consumer_app_id: consumerAppId });
  return requestJson<unknown>(`/api/apps/dependencies?${params.toString()}`).then((value) => {
    const payload = objectField(value);
    return {
      workspace_id: stringField(payload.workspace_id, "default"),
      consumer_app_id: stringField(payload.consumer_app_id, consumerAppId),
      status: stringField(payload.status, "unknown"),
      dependencies: Array.isArray(payload.dependencies)
        ? payload.dependencies.map(normalizeDependencyResolution).filter((item) => item.alias)
        : [],
    };
  });
}

export function selectedDependencyProviderAppId(payload: AppDependenciesPayload, alias: string): string {
  const dependency = payload.dependencies.find((item) => item.alias === alias);
  return selectedExplicitProviderIdsForDependency(dependency)[0] || "";
}

export function selectedSharedDependencyProviderAppId(payload: AppDependenciesPayload, aliases: string[]): string {
  const dependencies = aliases
    .map((alias) => payload.dependencies.find((item) => item.alias === alias))
    .filter((item): item is DependencyResolutionItem => Boolean(item));
  if (dependencies.length !== aliases.length) {
    return "";
  }
  const [primary, ...rest] = dependencies;
  for (const providerAppId of selectedProviderIdsForDependencyWithAutomaticFallback(primary)) {
    if (rest.every((dependency) => selectedProviderIdsForDependencyWithAutomaticFallback(dependency).includes(providerAppId))) {
      return providerAppId;
    }
  }
  return "";
}

function selectedExplicitProviderIdsForDependency(dependency: DependencyResolutionItem | undefined): string[] {
  if (!dependency) {
    return [];
  }
  const backendProviderIds = backendCandidateProviderIds(dependency);
  if (dependency.selected_provider_app_ids.length) {
    return dependency.selected_provider_app_ids.filter((providerAppId) => backendProviderIds.includes(providerAppId));
  }
  return [];
}

function selectedProviderIdsForDependencyWithAutomaticFallback(dependency: DependencyResolutionItem | undefined): string[] {
  const selectedProviderIds = selectedExplicitProviderIdsForDependency(dependency);
  if (selectedProviderIds.length || !dependency) {
    return selectedProviderIds;
  }
  const backendProviderIds = backendCandidateProviderIds(dependency);
  if (canUseAutomaticDependencyProvider(dependency)) {
    return backendProviderIds;
  }
  return [];
}

function canUseAutomaticDependencyProvider(dependency: DependencyResolutionItem): boolean {
  return (
    dependency.status === "optional_unset" &&
    dependency.cardinality === "one" &&
    dependency.stale_provider_app_ids.length === 0 &&
    !dependency.blocked_reason &&
    backendCandidateProviderIds(dependency).length > 0
  );
}

function backendCandidateProviderIds(dependency: DependencyResolutionItem): string[] {
  return dependency.candidates.filter((candidate) => candidate.surfaces.includes("backend")).map((candidate) => candidate.app_id);
}

function normalizeAgentType(value: unknown): AgentTypeSummary {
  const item = objectField(value);
  return {
    id: stringField(item.id),
    name: stringField(item.name),
    description: stringField(item.description),
    role_id: stringField(item.role_id),
    skill_ids: stringArrayField(item.skill_ids),
    trace_verbosity: stringField(item.trace_verbosity, "compact"),
    enabled: item.enabled !== false,
  };
}

export function listAgentCatalog(providerAppId: string): Promise<AgentCatalogPayload> {
  return requestJson<{ workspace_id?: string; agent_types?: unknown[] }>(`/api/apps/${encodeURIComponent(providerAppId)}/backend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "catalog.compact", entity_type: "agent_type", limit: 100 }),
  }).then((payload) => ({
    workspace_id: payload.workspace_id,
    agent_types: (payload.agent_types || []).map(normalizeAgentType).filter((item) => item.id && item.enabled),
  }));
}

export function getAgentDefinition(providerAppId: string, agentTypeId: string): Promise<AgentDefinitionPayload> {
  return requestJson<AgentDefinitionPayload>(`/api/apps/${encodeURIComponent(providerAppId)}/backend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "get_agent_definition", id: agentTypeId }),
  });
}

export function previewAgentPrompt(providerAppId: string, agentTypeId: string): Promise<AgentPromptPreviewPayload> {
  return requestJson<AgentPromptPreviewPayload>(`/api/apps/${encodeURIComponent(providerAppId)}/backend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "preview_prompt", agent_type_id: agentTypeId }),
  });
}

export async function listSkills(): Promise<SkillSummary[]> {
  const payload = await requestJson<{ skills?: SkillSummary[] }>("/api/apps/skills/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "catalog" }),
  });
  return (payload.skills || []).filter((skill) => skill.enabled);
}

export async function searchAppReferences(
  query: string,
  signal?: AbortSignal,
  options: SearchAppReferencesOptions = {},
): Promise<AppEntityReference[]> {
  const body: Record<string, unknown> = { query, limit: options.limit || 8 };
  const appIds = (options.appIds || []).map((appId) => appId.trim()).filter(Boolean);
  const entityTypes = (options.entityTypes || []).map((entityType) => entityType.trim()).filter(Boolean);
  if (appIds.length) {
    body.app_ids = appIds;
  }
  if (entityTypes.length) {
    body.entity_types = entityTypes;
  }
  const payload = await requestJson<{ items?: AppEntityReference[] }>("/api/app-references/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  return (payload.items || []).filter((item) => item.type === "entity" && item.app_id && item.entity_type && item.entity_id);
}
