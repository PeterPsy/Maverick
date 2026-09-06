import { describe, expect, it } from 'vitest';
import { groupAgenticProfileRevisions } from './agenticProfileGroups';
import { binding, freezeDeep, profile } from './agenticProfileTestFixtures';

describe('Settings agentic profile revisions', () => {
  it('renders one primary item for dozens of immutable revisions, without deleting history', () => {
    const items = Array.from({ length: 48 }, (_, index) => profile(String(index + 1)));
    const groups = groupAgenticProfileRevisions(items);
    expect(groups).toHaveLength(1);
    expect(groups[0].primary).toBe(items[47]);
    expect(groups[0].otherRevisions).toHaveLength(47);
    expect(new Set([groups[0].primary, ...groups[0].otherRevisions])).toEqual(new Set(items));
  });

  it('orders revisions numerically rather than placing 9 after 10', () => {
    const items = [profile('9'), profile('10'), profile('2')];
    expect(groupAgenticProfileRevisions(items)[0].primary).toBe(items[1]);
    expect(items.map((item) => item.definition_revision)).toEqual(['9', '10', '2']);
  });

  it('orders arbitrarily long numeric revisions without numeric precision or ICU limits', () => {
    const smaller = profile('9'.repeat(500));
    const larger = profile(`1${'0'.repeat(500)}`);
    for (const items of [[smaller, larger], [larger, smaller]]) {
      expect(groupAgenticProfileRevisions(items)[0].primary).toBe(larger);
    }
  });

  it('uses deterministic natural presentation ordering for nonnumeric labels', () => {
    const items = [profile('release-9'), profile('release-10'), profile('release-0010')];
    const first = groupAgenticProfileRevisions(items)[0];
    expect(first.primary.definition_revision).toBe('release-10');
    expect(groupAgenticProfileRevisions([...items].reverse())).toEqual([first]);
  });

  it('retains original frozen records, policy ceilings and certificate identities', () => {
    const items = freezeDeep([profile('15'), profile('14', { binding: binding(true, true) })]);
    const before = JSON.stringify(items);
    const grouped = groupAgenticProfileRevisions(items)[0];
    expect(grouped.primary).toBe(items[1]);
    expect(grouped.otherRevisions[0]).toBe(items[0]);
    expect(JSON.stringify(items)).toBe(before);
  });

  it('preserves the enabled workspace pin even when a newer candidate exists', () => {
    const active = profile('14', { binding: binding(true), selectable: true, blocked_reason: null });
    const candidate = profile('15');
    const group = groupAgenticProfileRevisions([candidate, active])[0];
    expect(group.primary).toBe(active);
    expect(group.otherRevisions).toEqual([candidate]);
    expect(candidate.enable_eligible).toBe(false);
    expect(candidate.blocked_reason).toBe('native_agent_connection_certificate_missing');
  });

  it('prefers the enabled default and retains every other enabled revision', () => {
    const current = profile('12', { binding: binding(true, true) });
    const another = profile('14', { binding: binding(true) });
    const latest = profile('15');
    const group = groupAgenticProfileRevisions([latest, another, current])[0];
    expect(group.primary).toBe(current);
    expect(group.otherRevisions).toContain(another);
    expect(group.otherRevisions).toContain(latest);
    expect(group.otherEnabledCount).toBe(1);
  });

  it('does not promote a disabled default over the latest unbound revision', () => {
    const old = profile('8', { binding: binding(false, true) });
    const latest = profile('14');
    expect(groupAgenticProfileRevisions([old, latest])[0].primary).toBe(latest);
  });

  it('does not collapse distinct profiles sharing a model and display name', () => {
    const items = [profile('14'), profile('3', { definition_id: 'codex:sol-restricted' })];
    expect(groupAgenticProfileRevisions(items)).toHaveLength(2);
  });

  it('keeps execution engines and model providers distinct', () => {
    const items = [profile('14'), profile('15', { runtime_engine_id: 'another-native' }),
      profile('16', { model_provider_id: 'another-provider' })];
    expect(groupAgenticProfileRevisions(items)).toHaveLength(3);
  });

  it('groups legacy Codex family metadata without granting new capabilities', () => {
    const old = profile('3', { execution_family: null });
    const current = profile('14');
    expect(groupAgenticProfileRevisions([old, current])[0].otherRevisions).toEqual([old]);
    expect(old.execution_family).toBeNull();
    expect(old.selectable).toBe(false);
  });

  it('keeps blocked API candidates visible without making them eligible', () => {
    const old = profile('9', { definition_id: 'google:flash', execution_family: 'maverick_agent' });
    const current = profile('46', { definition_id: 'google:flash', execution_family: 'maverick_agent',
      containment_status: 'NO-GO', containment_reason: 'hosted_agent_runtime_disabled' });
    const group = groupAgenticProfileRevisions([old, current])[0];
    expect(group.primary).toBe(current);
    expect(group.primary.containment_status).toBe('NO-GO');
    expect(group.primary.enable_eligible).toBe(false);
  });

  it('accepts an empty inventory', () => {
    expect(groupAgenticProfileRevisions([])).toEqual([]);
  });
});
