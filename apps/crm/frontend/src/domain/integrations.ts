import { useEffect } from 'react';
import { isExactMaverickParentMessage } from '@maverick/pwa-cache';
import { callBackend } from '../api';
import { Selection } from './vnext';

export type LinkedRef = { id: string; provider_alias: string; source_app_id: string; source_entity_type: string; source_entity_id: string; title: string; summary: string; metadata: { sync_enabled?: boolean; deep_link?: string; last_synced_at?: string; last_checked_at?: string; last_error?: string; resolution_status?: string; workspace_relative_path?: string; status?: string; task_id?: string; sections?: Array<{ id: string; title: string }> } };
export type ProviderReference = Omit<LinkedRef, 'id' | 'provider_alias' | 'source_app_id'>;
export type IntegrationOperation = { id: string; kind: string; status: string; approval_status?: string; provider_app_id: string; provider_alias: string; proposal_id: string; last_error: string; request: { body: Record<string, unknown> }; result: { references?: ProviderReference[]; external_ref?: LinkedRef; text?: string; review_proposal_id?: string } };
export const operationLabels: Record<string, string> = { mail_draft: 'Prepare email draft', calendar_event: 'Schedule meeting', document: 'Create document in Storage', checklist_task: 'Add Checklist task', task_status: 'Update Checklist task', transcription: 'Transcribe linked audio' };
export const operationAliases: Record<string, string> = { mail_draft: 'mail', calendar_event: 'calendar', document: 'file-write', checklist_task: 'tasks', task_status: 'tasks', transcription: 'speech' };
export async function completedOperation(body: Record<string, unknown>) {
  const response = await callBackend<{ operation: IntegrationOperation }>(body);
  const latest = await callBackend<{ operation: IntegrationOperation }>({ action: 'crm.integration_get', id: response.operation.id });
  if (latest.operation.status === 'failed' || latest.operation.status === 'uncertain') throw new Error(latest.operation.last_error);
  return latest.operation;
}
export function providerHref(ref: LinkedRef) {
  const link = ref.metadata.deep_link || '';
  return link.startsWith(`/app/${ref.source_app_id}/`) || link.startsWith(`/app/${ref.source_app_id}?`) || link === `/app/${ref.source_app_id}` ? link : `/app/${encodeURIComponent(ref.source_app_id)}`;
}

// Refresh only the visible CRM context on trusted, linked-provider changes.
// Coalesce bursts without polling; the backend owns freshness and in-flight locks.
export function useProviderRefresh(selected: Selection, refs: LinkedRef[]) {
  const providerKey = JSON.stringify([...new Set(refs.filter((ref) => ref.metadata.sync_enabled).map((ref) => ref.source_app_id))].sort());
  useEffect(() => {
    const providers: string[] = JSON.parse(providerKey);
    let timer: ReturnType<typeof setTimeout> | undefined;
    const changed = (event: MessageEvent) => {
      if (!isExactMaverickParentMessage(event) || event.data?.type !== 'maverick.app.data-changed' || !providers.includes(event.data?.owner_app_id) || timer) return;
      timer = setTimeout(() => {
        timer = undefined;
        void callBackend({ action: 'crm.integration_refresh', entity_type: selected.entity, entity_id: selected.record.id }).catch(() => { /* Last-good snapshot remains visible; explicit refresh exposes errors. */ });
      }, 5000);
    };
    window.addEventListener('message', changed);
    return () => { window.removeEventListener('message', changed); if (timer) clearTimeout(timer); };
  }, [providerKey, selected.entity, selected.record.id]);
}
