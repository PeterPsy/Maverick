import { CrmRecord } from '../api';
export { useLiveCrm } from './useCrmRead';

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
