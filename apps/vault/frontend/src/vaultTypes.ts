export type Tab = 'secrets' | 'grants' | 'audit';
export type GrantTargetMode = 'app_backend';
export type GrantAction = 'app.backend';

export type ShellNavigatePayload = {
  app_id?: string;
  params?: Record<string, string | boolean | null>;
  type?: string;
};

export const GRANT_ACTIONS = [
  { value: 'app.backend', label: 'Backend' }
] as const;
