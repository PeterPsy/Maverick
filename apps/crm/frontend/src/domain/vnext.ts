import { useEffect, useState } from 'react';
import { isExactMaverickParentMessage } from '@maverick/pwa-cache';
import { callBackend, CrmRecord } from '../api';

export const extensionPages: Record<string, { title: string; description: string; entities: string[] }> = {
  conversations: { title: 'Conversations', description: 'Keep the context. Connect people, decisions and the next step.', entities: ['conversation_thread'] },
  campaigns: { title: 'Campaigns', description: 'Plan an audience, compare variants and build a thoughtful sequence. Nothing sends automatically.', entities: ['campaign'] },
  expenses: { title: 'Expenses', description: 'Track costs in their original currency and connect them to your business.', entities: ['expense'] },
  intelligence: { title: 'Intelligence', description: 'Your market knowledge, competitive research and periodic briefs.', entities: ['intelligence_profile', 'brief'] },
  objects: { title: 'Custom objects', description: 'Model the resources your business needs, without imposing an industry.', entities: ['custom_object_record', 'custom_object_definition'] },
};
export const extensionEntities = ['conversation_thread', 'campaign', 'campaign_variant', 'campaign_step', 'campaign_member', 'campaign_event', 'expense', 'brief', 'intelligence_profile', 'custom_object_definition', 'custom_object_record'];
export const allEntities = ['lead', 'account', 'contact', 'deal', 'activity', 'task', 'note', ...extensionEntities];
export const extensionRoutes: Record<string, string> = { conversation_thread: 'conversation_threads', campaign: 'campaigns', campaign_variant: 'campaign_variants', campaign_step: 'campaign_steps', campaign_member: 'campaign_members', campaign_event: 'campaign_events', expense: 'expenses', brief: 'briefs', intelligence_profile: 'intelligence_profiles', custom_object_definition: 'custom_object_definitions', custom_object_record: 'custom_object_records' };
export const label = (value: string) => value.replace(/_/g, ' ').replace(/^./, (letter) => letter.toUpperCase());
export type ExtensionSpec = { fields: Record<string, string>; defaults?: Record<string, unknown>; required?: string[] };
export type ExtensionSchema = { entities: Record<string, ExtensionSpec> };
export type Selection = { entity: string; record: CrmRecord };
export type Provider = { alias: string; interface: string; configured: boolean; selected_provider_app_ids: string[]; linked_count: number };

// These are live-only reads. New fields and workflow authority do not widen the
// platform-reviewed persistent PWA display schemas.
export function useLiveCrm<T>(request: Record<string, unknown>) {
  const key = JSON.stringify(request);
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const refresh = () => setRevision((value) => value + 1);
  useEffect(() => {
    let active = true;
    setLoading(true); setError('');
    callBackend<T>(JSON.parse(key)).then((value) => { if (active) setData(value); })
      .catch((failure) => { if (active) setError(failure instanceof Error ? failure.message : 'Unable to load CRM data.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [key, revision]);
  useEffect(() => {
    const changed = (event: MessageEvent) => {
      if (isExactMaverickParentMessage(event) && event.data?.type === 'maverick.app.data-changed' && event.data?.owner_app_id === 'crm') refresh();
    };
    window.addEventListener('message', changed);
    window.addEventListener('crm-workspace-refresh', refresh);
    return () => { window.removeEventListener('message', changed); window.removeEventListener('crm-workspace-refresh', refresh); };
  }, []);
  return { data, error, loading, refresh };
}
