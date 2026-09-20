export type SkillSummary = {
  id: string;
  local_id: string;
  name: string;
  description: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  origin: string;
  remote_id: string;
  source_url: string;
  source_content_sha256: string;
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

export type RemoteSkillSummary = {
  id: string;
  slug: string;
  title: string;
  description: string;
  author: string;
  files: string[];
  link: string;
};

export type RemoteSkillFile = {
  filename: string;
  content: string;
};

export type RemoteSkillDetail = Omit<RemoteSkillSummary, 'files'> & {
  files: RemoteSkillFile[];
  updated_at: string;
  content_sha256: string;
  content_trust: 'untrusted_external' | string;
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
