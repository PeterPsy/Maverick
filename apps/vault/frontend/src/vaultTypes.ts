export type Tab = 'credentials' | 'issues' | 'advanced';
export type CredentialPanel = 'edit' | 'new' | '';

export type ShellNavigatePayload = {
  app_id?: string;
  params?: Record<string, string | boolean | null>;
  type?: string;
};
