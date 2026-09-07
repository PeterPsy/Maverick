import { describe, expect, it } from 'vitest';
import type { AgenticAdminItem } from './adminApi';
import { deduplicateAgenticModels } from './agenticModelSelection';

function profile(revision: string, options: Partial<AgenticAdminItem> = {}): AgenticAdminItem {
  return {
    definition_id: 'codex:sol', definition_revision: revision,
    execution_family: 'native_agent', runtime_engine_id: 'codex', model_provider_id: 'codex',
    model_id: 'gpt-5.6-sol', display_name: 'Codex · gpt-5.6-sol',
    binding: null, selectable: false, enable_eligible: false,
    full_workspace_status: 'unavailable',
    blocked_reason: 'native_agent_connection_certificate_missing',
    ...options,
  } as AgenticAdminItem;
}

function binding(enabled: boolean, isDefault = false): AgenticAdminItem['binding'] {
  return { binding_id: 'workspace-pin', revision: 7, enabled, is_default: isDefault } as AgenticAdminItem['binding'];
}

describe('Settings agentic models', () => {
  it('returns one item for dozens of revisions of the same model', () => {
    const items = Array.from({ length: 48 }, (_, index) => profile(String(index + 1)));
    expect(deduplicateAgenticModels(items)).toEqual([items[47]]);
    expect(items.map((item) => item.definition_revision)).toEqual(
      Array.from({ length: 48 }, (_, index) => String(index + 1)),
    );
  });

  it('orders revisions naturally rather than placing 9 after 10', () => {
    const items = [profile('9'), profile('10'), profile('2')];
    expect(deduplicateAgenticModels(items)).toEqual([items[1]]);
  });

  it('preserves an enabled workspace pin even when a newer candidate exists', () => {
    const active = profile('14', { binding: binding(true), selectable: true, blocked_reason: null });
    const candidate = profile('15');
    expect(deduplicateAgenticModels([candidate, active])).toEqual([active]);
  });

  it('prefers the enabled default over another enabled profile', () => {
    const current = profile('12', { binding: binding(true, true) });
    const newer = profile('15', { binding: binding(true) });
    expect(deduplicateAgenticModels([newer, current])).toEqual([current]);
  });

  it('does not promote a disabled default over the latest profile', () => {
    const old = profile('8', { binding: binding(false, true) });
    const latest = profile('14');
    expect(deduplicateAgenticModels([old, latest])).toEqual([latest]);
  });

  it('prefers a certified, enable-eligible profile over a newer broken profile', () => {
    const certified = profile('8', {
      definition_id: 'codex:sol-certified',
      enable_eligible: true,
      full_workspace_status: 'certified',
    });
    const broken = profile('99', { definition_id: 'codex:sol-broken' });
    expect(deduplicateAgenticModels([broken, certified])).toEqual([certified]);
  });

  it('collapses distinct definitions and runtime engines for the same model and category', () => {
    const items = [
      profile('14'),
      profile('15', { definition_id: 'codex:sol-alternative', runtime_engine_id: 'another-native' }),
    ];
    expect(deduplicateAgenticModels(items)).toEqual([items[1]]);
  });

  it('keeps providers, models, and CLI/API categories distinct', () => {
    const items = [
      profile('14'),
      profile('15', { model_provider_id: 'another-provider' }),
      profile('16', { model_id: 'gpt-5.6-terra' }),
      profile('17', { execution_family: 'maverick_agent' }),
    ];
    expect(deduplicateAgenticModels(items)).toEqual(items);
  });

  it('groups legacy Codex family metadata with the native category', () => {
    const old = profile('3', { execution_family: null });
    const current = profile('14');
    expect(deduplicateAgenticModels([old, current])).toEqual([current]);
    expect(old.execution_family).toBeNull();
  });

  it('keeps the latest blocked API candidate without making it eligible', () => {
    const old = profile('9', {
      definition_id: 'google:flash-old', execution_family: 'maverick_agent',
      model_provider_id: 'google-ai-studio', model_id: 'gemini-3.6-flash',
    });
    const current = profile('46', {
      definition_id: 'google:flash-current', execution_family: 'maverick_agent',
      model_provider_id: 'google-ai-studio', model_id: 'gemini-3.6-flash',
      containment_status: 'NO-GO', containment_reason: 'hosted_agent_runtime_disabled',
    });
    expect(deduplicateAgenticModels([old, current])).toEqual([current]);
    expect(current.enable_eligible).toBe(false);
  });

  it('accepts an empty inventory', () => {
    expect(deduplicateAgenticModels([])).toEqual([]);
  });
});
