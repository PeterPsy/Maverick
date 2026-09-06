/** Synthetic UI records only: never operational certificates or authority. */
import type { AgenticAdminItem, AgenticRuntimePolicy, PlatformSettings } from './adminApi';

function policy(): AgenticRuntimePolicy {
  return {
    max_steps_per_turn: 10, max_tool_calls_per_turn: 10, max_parallel_tool_calls: 1,
    max_wall_time_seconds: 60, max_tool_result_bytes: 1024, max_total_tool_result_bytes: 4096,
    max_input_tokens: 8192, max_output_tokens: 1024, max_estimated_cost_microusd: 300_000,
    allowed_surface_kinds: [], allowed_tool_handles: [], tool_handle_mode: 'none',
    allow_filesystem_list: false, allow_filesystem_read: false, allow_filesystem_write: false,
    allow_shell: false, require_confirmation_for_mutating: true,
    require_confirmation_for_destructive: true, allowed_remote_data_classes: [],
  };
}

export function binding(enabled: boolean, isDefault = false): NonNullable<AgenticAdminItem['binding']> {
  return {
    binding_id: 'workspace-pin', revision: 7, enabled, is_default: isDefault,
    credential_binding_id: null, actor_policy: {
      allow_workspace_admins: true, allowed_user_ids: [],
      allowed_workspace_role_ids: ['member'], allowed_agent_type_ids: [],
    },
    workspace_policy_ceiling: policy(), egress_policy_id: 'ui-only', egress_policy_revision: '1',
    created_at: '2026-09-06T00:00:00Z', updated_at: '2026-09-06T00:00:00Z',
  };
}

export function profile(revision: string, options: Partial<AgenticAdminItem> = {}): AgenticAdminItem {
  return {
    definition_id: 'codex:sol', definition_revision: revision,
    execution_family: 'native_agent', runtime_engine_id: 'codex', model_provider_id: 'codex',
    model_id: 'gpt-5.6-sol', display_name: 'Codex · gpt-5.6-sol',
    provider_protocol: 'codex-app-server-stdio', provider_api_version: '1',
    adapter_id: 'codex-app-server', adapter_version_constraint: '==1',
    binding: null, selectable: false, enable_eligible: false,
    blocked_reason: 'native_agent_connection_certificate_missing',
    enable_blocked_reason: 'native_agent_connection_certificate_missing',
    family_contract_status: 'complete', family_contract_reason: null,
    full_workspace_status: 'unavailable', full_workspace_contract_revision: null,
    harness_recipe: { id: 'ui-only', revision: '1', digest: 'ui-only' },
    routing_constraint: { endpoint_id: 'local', allowed_upstream_ids: [],
      allow_fallbacks: false, require_parameters: true, data_collection_policy: 'deny',
      require_zdr: false, allowed_quantizations: [] },
    profile_policy_ceiling: policy(), rollout_status: 'preview', certificate: null,
    credential_bindings: [], health: 'blocked', containment_status: 'GO', containment_reason: null,
    binding_status: 'missing', profile_status: 'published', certificate_eligibility: 'missing',
    upstream_provider_ids: [], data_destination: {
      provider_id: 'codex', endpoint_id: 'local', upstream_provider_ids: [], display_label: 'Local',
    },
    egress_policy: { policy_id: 'ui-only', revision: '1', allowed_remote_data_classes: [] },
    data_policy: { collection: 'deny', require_zdr: false, attestation_state: 'not_attested' },
    ...options,
  };
}

export function settings(items: AgenticAdminItem[]): PlatformSettings {
  const provider = {
    workspace_id: 'ui-test', active_provider: null, selection: null, model_settings: null,
  };
  return {
    user: { user_id: 'ui-test', display_name: 'UI test', username: 'ui-test',
      platform_role: 'admin', email: null, account_type: 'human' },
    workspace: { workspace_id: 'ui-test', name: 'Synthetic UI', description: null,
      status: 'active', governance: {}, quota: {}, is_active: true },
    provider, runtime: { ...provider, sessions: [] }, recovery: {},
    agentic_admin: { workspace_id: 'ui-test', release_decision: 'GO', items },
  };
}

export function freezeDeep<T>(value: T): T {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(freezeDeep);
    Object.freeze(value);
  }
  return value;
}
