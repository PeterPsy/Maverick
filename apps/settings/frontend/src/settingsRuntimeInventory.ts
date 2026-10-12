import type { PlatformSettings, RuntimeCleanupPayload, RuntimeSessionInventoryPayload } from './adminApi';

export function mergeRuntimeSessionInventory(
  settings: PlatformSettings,
  inventory: RuntimeSessionInventoryPayload | RuntimeCleanupPayload | null,
): PlatformSettings {
  if (!inventory) {
    return settings;
  }
  const items = 'items' in inventory ? inventory.items : inventory.sessions;
  const cleanupAllowed = 'cleanup_allowed' in inventory ? inventory.cleanup_allowed : settings.runtime.cleanup_allowed;
  const cleanupScope = 'cleanup_scope' in inventory ? inventory.cleanup_scope : settings.runtime.cleanup_scope;
  return {
    ...settings,
    runtime: {
      ...settings.runtime,
      all_sessions: items || [],
      cleanup_allowed: cleanupAllowed,
      cleanup_scope: cleanupScope,
    },
  };
}
