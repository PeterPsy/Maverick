import type { DynamicViewCreatePayload, DynamicViewInstance, DynamicViewPayload, DynamicViewsListPayload } from './types';

export async function callBackend<T>(body: Record<string, unknown>): Promise<T> {
  const response = await fetch('/api/apps/dynamic-views/backend', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || payload.error || 'Dynamic Views request failed');
  return payload as T;
}

export function listDynamicViews() {
  return callBackend<DynamicViewsListPayload>({ action: 'list' });
}

export function createDynamicView(payload: DynamicViewCreatePayload) {
  return callBackend<{ instance: DynamicViewInstance; chat_render: { payload: DynamicViewPayload } }>({
    action: 'create',
    payload
  });
}

export function readDynamicView(instanceId: string) {
  return callBackend<{ instance: DynamicViewInstance; chat_render: { payload: DynamicViewPayload } }>({
    action: 'read',
    id: instanceId
  });
}

export function deleteDynamicView(instanceId: string) {
  return callBackend<{ status: string; deleted: number }>({ action: 'delete', id: instanceId });
}

export function toDynamicViewPayload(instance: DynamicViewInstance): DynamicViewPayload {
  return {
    id: instance.id,
    instanceId: instance.id,
    title: instance.title,
    summary: instance.summary || undefined,
    snapshotMode: instance.snapshot_mode,
    package: {
      id: instance.package.id,
      title: instance.package.title,
      summary: instance.package.summary || undefined,
      renderer: instance.package.renderer,
      html: instance.package.html,
      css: instance.package.css,
      javascript: instance.package.javascript,
      securityReport: instance.package.security_report,
      tags: instance.package.tags
    },
    data: instance.data,
    dataBindings: instance.data_bindings.map((binding) => ({
      sourceType: binding.source_type,
      sourceRef: binding.source_ref,
      query: binding.query ?? null,
      snapshot: binding.snapshot ?? null
    })),
    createdAt: instance.created_at,
    updatedAt: instance.updated_at
  };
}
