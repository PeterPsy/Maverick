import type { Candidate, Filters, Stats, ViewState } from './types';
const ENDPOINT = '/api/apps/videomaker-selection/backend';

async function request<T>(body: Record<string, unknown>): Promise<T> {
  const response = await fetch(ENDPOINT, {method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data = await response.json() as T & {error?:string;detail?:string};
  if (!response.ok || data.error) throw new Error(data.detail || data.error || 'Richiesta non riuscita.');
  return data;
}
export async function listCandidates(filters: Filters): Promise<Candidate[]> {
  const data = await request<{items:Candidate[]}>({action:'list',limit:500,...filters,favorite:filters.favorite || undefined});
  return data.items || [];
}
export async function readCandidate(id:string): Promise<Candidate> {
  const data=await request<{candidate:Candidate}>({action:'read',id}); return data.candidate;
}
export async function readStats(): Promise<Stats> {
  const data=await request<{stats:Stats}>({action:'stats'}); return data.stats;
}
export async function createCandidate(payload:Partial<Candidate>): Promise<Candidate> {
  const data=await request<{candidate:Candidate}>({action:'create',payload}); return data.candidate;
}
export async function updateCandidate(id:string,payload:Partial<Candidate>): Promise<Candidate> {
  const data=await request<{candidate:Candidate}>({action:'update',id,payload}); return data.candidate;
}
export async function bulkUpdate(ids:string[],payload:Partial<Candidate>): Promise<Candidate[]> {
  const data=await request<{candidates:Candidate[]}>({action:'bulk_update',ids,payload}); return data.candidates;
}
export async function deleteCandidate(id:string): Promise<void> { await request({action:'delete',id,confirm:true}); }
export async function addActivity(id:string,summary:string): Promise<Candidate> {
  const data=await request<{candidate:Candidate}>({action:'activity.add',id,kind:'note',summary}); return data.candidate;
}
export async function exportCatalog(): Promise<Record<string,unknown>> {
  const data=await request<{export:Record<string,unknown>}>({action:'export'}); return data.export;
}
export async function readViewState(): Promise<ViewState> {
  const data=await request<{view_state:ViewState}>({action:'view_filter'}); return data.view_state;
}
export async function saveViewState(query:string,decision:string): Promise<ViewState> {
  const data=await request<{view_state:ViewState}>({action:'set_view_filter',query,decision}); return data.view_state;
}
