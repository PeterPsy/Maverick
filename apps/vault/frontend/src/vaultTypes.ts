export type Tab = 'credentials' | 'issues' | 'import' | 'advanced';

export type ShellNavigatePayload = {
  app_id?: string;
  params?: Record<string, string | boolean | null>;
  type?: string;
};
