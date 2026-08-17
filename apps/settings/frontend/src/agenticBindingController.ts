import {
  configureAgenticWorkspaceBinding,
  getPlatformSettings,
  type PlatformSettings
} from './adminApi';
import { syncSettingsPanelDraft, type SettingsPanelState } from './settingsPanel';

type AgenticBindingControllerContext = {
  getSettings: () => PlatformSettings | null;
  render: () => void;
  setSettings: (settings: PlatformSettings, message: string) => void;
  state: SettingsPanelState;
};

export function createAgenticBindingController(context: AgenticBindingControllerContext) {
  return {
    save: async (definitionId: string, definitionRevision: string) => {
      const key = `${definitionId}:${definitionRevision}`;
      const item = context.getSettings()?.agentic_admin?.items.find(
        (candidate) => candidate.definition_id === definitionId
          && candidate.definition_revision === definitionRevision
      );
      const form = Array.from(document.querySelectorAll<HTMLElement>('[data-agentic-binding-form]')).find(
        (candidate) => candidate.dataset.agenticDefinitionId === definitionId
          && candidate.dataset.agenticDefinitionRevision === definitionRevision
      );
      if (!item || !form) {
        context.state.agenticBindingErrors[key] = 'Agentic binding form is no longer available.';
        context.render();
        return;
      }
      const field = <T extends HTMLInputElement | HTMLSelectElement>(name: string) =>
        form.querySelector<T>(`[data-agentic-field="${name}"]`);
      const checked = (name: string) => Boolean(field<HTMLInputElement>(name)?.checked);
      const costValue = field<HTMLInputElement>('max_estimated_cost_usd')?.value.trim() || '';
      const parsedCostMicrousd = Math.round(Number(costValue) * 1_000_000);
      if (costValue && (!Number.isFinite(parsedCostMicrousd) || parsedCostMicrousd < 0)) {
        context.state.agenticBindingErrors[key] = 'Maximum cost must be a non-negative amount.';
        context.render();
        return;
      }
      const allowedRemoteDataClasses = [
        ...(checked('allow_public_data') ? ['public'] : []),
        ...(checked('allow_fake_data') ? ['workspace_internal_fake'] : [])
      ];
      context.state.savingAgenticBindings.add(key);
      context.state.agenticBindingErrors[key] = '';
      context.render();
      try {
        await configureAgenticWorkspaceBinding({
          definition_id: definitionId,
          definition_revision: definitionRevision,
          binding_id: item.binding?.binding_id || null,
          expected_revision: item.binding?.revision ?? null,
          credential_binding_id: field<HTMLSelectElement>('credential_binding_id')?.value || null,
          enabled: checked('enabled'),
          is_default: checked('is_default'),
          actor_policy: {
            allow_workspace_admins: checked('allow_workspace_admins'),
            allowed_user_ids: item.binding?.actor_policy.allowed_user_ids || [],
            allowed_workspace_role_ids: checked('allow_workspace_members') ? ['member'] : [],
            allowed_agent_type_ids: item.binding?.actor_policy.allowed_agent_type_ids || []
          },
          policy_patch: {
            max_estimated_cost_microusd: costValue ? parsedCostMicrousd : null,
            tool_access_enabled: checked('tool_access_enabled'),
            require_confirmation_for_mutating: checked('require_confirmation_for_mutating'),
            require_confirmation_for_destructive: checked('require_confirmation_for_destructive'),
            allowed_remote_data_classes: allowedRemoteDataClasses
          },
          confirm_fake_data_only_workspace: checked('confirm_fake_data_only_workspace')
        });
        const settings = await getPlatformSettings();
        syncSettingsPanelDraft(context.state, settings);
        context.setSettings(settings, `${item.display_name} binding updated for new sessions.`);
      } catch (error) {
        context.state.agenticBindingErrors[key] = error instanceof Error
          ? error.message
          : 'Unable to save agentic binding.';
      } finally {
        context.state.savingAgenticBindings.delete(key);
        context.render();
      }
    }
  };
}
