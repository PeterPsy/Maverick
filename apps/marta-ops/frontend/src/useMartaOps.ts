import { useCallback, useEffect, useState } from 'react';
import { callBackend } from './api';
import type { BackendPayload, MartaOpsState } from './types';

const EMPTY_STATE: MartaOpsState = { schema_version: '1', collaborations: [], ideas: [] };

export function useMartaOps() {
  const [state, setState] = useState<MartaOpsState>(EMPTY_STATE);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    try {
      const payload = await callBackend<BackendPayload>({ action: 'bootstrap' });
      setState(payload.state);
      setError('');
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Impossibile caricare Marta Ops.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') return;
      const message = event.data as { type?: string; owner_app_id?: string; resource?: string };
      if (message.type === 'maverick.app.data-changed' && message.owner_app_id === 'marta-ops' && message.resource === 'state') {
        void refresh();
      }
    };
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [refresh]);

  const mutate = useCallback(async (body: Record<string, unknown>) => {
    setSaving(true);
    try {
      const payload = await callBackend<BackendPayload>(body);
      setState(payload.state);
      setError('');
      return payload;
    } catch (mutationError) {
      const message = mutationError instanceof Error ? mutationError.message : 'Operazione non riuscita.';
      setError(message);
      throw mutationError;
    } finally {
      setSaving(false);
    }
  }, []);

  return { state, loading, saving, error, clearError: () => setError(''), mutate, refresh };
}
