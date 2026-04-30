import type { DocsBackendResponse, DocsState } from './types';

async function callDocsBackend(body: Record<string, unknown>): Promise<DocsBackendResponse> {
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
  return payload as DocsBackendResponse;
}

export async function loadDocsState(): Promise<DocsState> {
  const payload = await callDocsBackend({ action: 'get-state' });
  if (!payload.state) {
    throw new Error('Docs Studio did not return state.');
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
