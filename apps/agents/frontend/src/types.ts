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
