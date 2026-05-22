export type Tab = 'readiness' | 'secrets' | 'grants' | 'audit';
export type GrantTargetMode = 'app_backend_all' | 'app_backend' | 'app_cli' | 'app_mcp' | 'custom';
export type GrantAction = 'app.backend';

export type ShellNavigatePayload = {
  app_id?: string;
  params?: Record<string, string | boolean | null>;
  type?: string;
};

export const GRANT_ACTIONS = [
  { value: 'app.backend', label: 'Backend' }
] as const;

export const GRANT_TARGET_MODES: Array<{ value: GrantTargetMode; label: string }> = [
  { value: 'app_backend_all', label: 'All app surfaces' },
  { value: 'app_backend', label: 'Backend only' },
  { value: 'app_cli', label: 'CLI command' },
  { value: 'app_mcp', label: 'MCP tool' },
  { value: 'custom', label: 'Custom target' }
];
