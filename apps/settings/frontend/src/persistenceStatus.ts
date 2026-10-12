import { requestJson, type PersistenceStatus } from './adminApi';

export async function requestPersistenceStatusQuiet(): Promise<PersistenceStatus | null> {
  try { return await requestJson<PersistenceStatus>('/api/admin/persistence'); }
  catch { return null; }
}
