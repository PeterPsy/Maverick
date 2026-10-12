import type { PlatformSettings } from './adminApi';

export function mergeSettingsSnapshot(current: PlatformSettings | null, next: PlatformSettings, section: string): PlatformSettings {
  if (current?.workspace.workspace_id !== next.workspace.workspace_id) current = null;
  const provider = section === 'models' ? next.provider : section === 'voice'
    ? { ...(current?.provider || next.provider), hosted_text: next.provider.hosted_text, speech_stt: next.provider.speech_stt }
    : current?.provider || next.provider;
  return { ...current, ...next, provider,
    runtime: { ...current?.runtime, ...next.runtime, all_sessions: current?.runtime.all_sessions },
    computer_use: next.computer_use || current?.computer_use,
    agentic_admin: section === 'models' ? next.agentic_admin : current?.agentic_admin,
  };
}
