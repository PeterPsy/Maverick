import type { AgenticAdminItem } from './adminApi';

const naturalOrder = new Intl.Collator('en', { numeric: true, sensitivity: 'variant' });

/**
 * Return the single profile Settings should show for each model in an execution family.
 * Dedicated admin APIs may expose full history; keep the UI defensive when they do.
 */
export function deduplicateAgenticModels(items: readonly AgenticAdminItem[]): AgenticAdminItem[] {
  const models = new Map<string, AgenticAdminItem>();
  for (const item of items) {
    const key = agenticModelKey(item);
    const current = models.get(key);
    if (!current || compareProfiles(item, current) > 0) {
      models.set(key, item);
    }
  }
  return Array.from(models.values());
}

function agenticModelKey(item: AgenticAdminItem): string {
  const family = item.execution_family
    || (item.runtime_engine_id === 'codex' ? 'native_agent' : 'unclassified');
  return JSON.stringify([family, item.model_provider_id, item.model_id]);
}

function compareProfiles(left: AgenticAdminItem, right: AgenticAdminItem): number {
  return profilePriority(left) - profilePriority(right)
    || naturalOrder.compare(left.definition_revision, right.definition_revision)
    || naturalOrder.compare(left.definition_id, right.definition_id);
}

function profilePriority(item: AgenticAdminItem): number {
  if (item.binding?.enabled && item.binding.is_default) return 5;
  if (item.binding?.enabled) return 4;
  if (item.selectable) return 3;
  if (item.enable_eligible) return 2;
  if (item.full_workspace_status === 'certified') return 1;
  return 0;
}
