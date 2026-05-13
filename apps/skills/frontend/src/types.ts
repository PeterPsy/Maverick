export type SkillSummary = {
  id: string;
  local_id: string;
  name: string;
  description: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  origin: string;
  source_path: string;
  editable: boolean;
  deletable: boolean;
};

export type SkillDetail = SkillSummary & {
  content: string;
  markdown: string;
};

export type Catalog = {
  skills: SkillSummary[];
};

export type SkillEdits = {
  name: string;
  description: string;
  content: string;
  enabled: boolean;
};

export type ViewFilter = {
  mode?: string;
  query?: string;
  entity_type?: string;
};

export type ViewFilterPayload = {
  state?: {
    view_filter?: ViewFilter;
  };
};
