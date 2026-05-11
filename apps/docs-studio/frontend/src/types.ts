export interface DocsSite {
  name: string;
  logo: string;
  accent: string;
  tagline: string;
}

export interface DocsPage {
  id: string;
  title: string;
  icon: string;
  summary: string;
  body: string;
  updated_at?: string;
  source_app_id?: string;
  source_doc_id?: string;
  source_path?: string;
}

export interface DocsSection {
  id: string;
  title: string;
  pages: DocsPage[];
}

export interface DocsState {
  schema_version: string;
  site: DocsSite;
  view_state?: DocsViewState;
  sections: DocsSection[];
}

export interface DocsBackendResponse {
  ok?: boolean;
  state?: DocsState;
  page?: DocsPage;
  view_state?: DocsViewState;
  error?: string;
}

export interface DocsViewState {
  query?: string;
  section_id?: string | null;
  custom_page_ids?: string[];
}
