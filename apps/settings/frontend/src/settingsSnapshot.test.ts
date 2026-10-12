import { expect, it } from 'vitest';
import { mergeSettingsSnapshot } from './settingsSnapshot';
import type { PlatformSettings } from './adminApi';

it('keeps the model catalog and session inventory when Voice returns a partial projection', () => {
  const current = { workspace: { workspace_id: 'default' }, provider: { native_agents: { items: [{ label: 'Codex' }] } },
    runtime: { all_sessions: [{ session_id: 'kept' }] }, agentic_admin: { items: [{ definition_id: 'model' }] },
  } as unknown as PlatformSettings;
  const voice = { workspace: current.workspace, provider: { active_provider: null, speech_stt: { model_settings: { audio_transcription_model_id: 'new' } } }, runtime: { sessions: [] } } as unknown as PlatformSettings;
  const merged = mergeSettingsSnapshot(current, voice, 'voice');
  expect(merged.provider.native_agents).toEqual(current.provider.native_agents);
  expect(merged.agentic_admin).toBe(current.agentic_admin);
  expect(merged.runtime.all_sessions).toBe(current.runtime.all_sessions);
  expect(merged.provider.speech_stt).toBe(voice.provider.speech_stt);
});

it('drops previous workspace data and obsolete administrative authority', () => {
  const current = { workspace: { workspace_id: 'old' }, provider: { native_agents: { items: [{ label: 'Old' }] } },
    runtime: { all_sessions: [{ session_id: 'old' }] }, agentic_admin: { items: [] }, computer_use: { workspace_id: 'old' },
  } as unknown as PlatformSettings;
  const next = { workspace: { workspace_id: 'new' }, provider: { active_provider: null }, runtime: { sessions: [] } } as unknown as PlatformSettings;
  const merged = mergeSettingsSnapshot(current, next, 'context');
  expect(merged.provider.native_agents).toBeUndefined();
  expect(merged.runtime.all_sessions).toBeUndefined();
  expect(merged.agentic_admin).toBeUndefined();
  expect(merged.computer_use).toBeUndefined();
});
