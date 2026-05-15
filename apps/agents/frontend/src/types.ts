export type Role = {
  id: string;
  name: string;
  description: string;
  instructions: string;
};

export type AgentType = {
  id: string;
  name: string;
  description: string;
  role_id: string;
  skill_ids: string[];
  trace_verbosity: string;
  enabled: boolean;
};

export type SkillSummary = {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
};

export type DependencyProviderCandidate = {
  app_id: string;
  name: string;
  version: string;
  interface: string;
  interface_version: string;
  description: string;
  surfaces: string[];
};

export type DependencyResolutionItem = {
  alias: string;
  interface: string;
  version: string;
  required: boolean;
  cardinality: 'one' | 'many';
  description: string;
  status: string;
  candidates: DependencyProviderCandidate[];
  selected_provider_app_ids: string[];
  stale_provider_app_ids: string[];
  blocked_reason: string | null;
};

export type AppDependenciesPayload = {
  workspace_id: string;
  consumer_app_id: string;
  status: string;
  dependencies: DependencyResolutionItem[];
};

export type Catalog = {
  common_prompt: string;
  roles: Role[];
  agent_types: AgentType[];
};

export type Preview = {
  rendered: string;
};

export type AgentEdits = {
  name: string;
  description: string;
  instructions: string;
  commonPrompt: string;
  skillIds: string[];
};
