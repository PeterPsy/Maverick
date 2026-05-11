import type { DocsBackendResponse, DocsNavigationState, DocsState, DocsViewState } from './types';

type DocsNavigationResponse = Omit<DocsBackendResponse, 'state'> & { state?: DocsNavigationState };

export async function callDocsBackend<T extends { ok?: boolean; error?: string } = DocsBackendResponse>(
  body: Record<string, unknown>
): Promise<T> {
  const response = await fetch('/api/apps/docs-studio/backend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const raw = await response.json();
  const payload = raw && raw.json ? raw.json : raw;
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || 'Docs Studio request failed');
  }
  return payload as T;
}

export async function loadDocsState(): Promise<DocsState> {
  const payload = await callDocsBackend({ action: 'get-state' });
  if (!payload.state) {
    throw new Error('Docs Studio did not return state.');
  }
  return payload.state;
}

export async function loadDocsNavigationState(): Promise<DocsNavigationState> {
  const payload = await callDocsBackend<DocsNavigationResponse>({ action: 'get-navigation' });
  if (!payload.state) {
    throw new Error('Docs Studio did not return navigation state.');
  }
  return payload.state;
}

export async function saveDocsPage(input: {
  page_id: string;
  title: string;
  summary: string;
  body: string;
}): Promise<DocsState> {
  const payload = await callDocsBackend({ action: 'update-page', ...input });
  if (!payload.state) {
    throw new Error('Docs Studio did not return updated state.');
  }
  return payload.state;
}

export async function createDocsPage(input: {
  section_id: string;
  title: string;
  summary: string;
  body: string;
}): Promise<DocsBackendResponse> {
  return callDocsBackend({ action: 'create-page', ...input });
}

export async function readDocsViewFilter(): Promise<DocsViewState> {
  const payload = await callDocsBackend({ action: 'view_filter' });
  return payload.view_state || {};
}

export async function setDocsViewFilter(query: string, sectionId?: string | null): Promise<DocsViewState> {
  const payload = await callDocsBackend({ action: 'set_view_filter', query, section_id: sectionId || null });
  return payload.view_state || {};
}
