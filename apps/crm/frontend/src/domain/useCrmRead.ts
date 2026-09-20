import { useCallback, useEffect, useState } from 'react';
import { isExactMaverickParentMessage, type AppReadModelOptions } from '@maverick/pwa-cache';
import { callBackend } from '../api';
import { readCrmDisplay } from '../pwaCache';

const readLive = <T,>(request: Record<string, unknown>, options: AppReadModelOptions<T> = {}) =>
  callBackend<T>(request, options.signal);

// Only reviewed display projections use the cache. Workflow and extension reads
// use the same request lifecycle, but stay live and cannot gain replay authority.
export function useLiveCrm<T>(request: Record<string, unknown>) {
  return useCrmRead<T>(request, readLive);
}

export function useCrmDisplay<T>(parameters: Record<string, unknown>) {
  return useCrmRead<T>(parameters, readCrmDisplay);
}

function useCrmRead<T>(request: Record<string, unknown>, read: typeof readCrmDisplay) {
  const key = JSON.stringify(request);
  const [state, setState] = useState({ key, data: null as T | null, error: '', loading: true });
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    let revalidated = false;
    setState((current) => ({ key, data: current.key === key ? current.data : null, error: '', loading: current.key !== key || current.data === null }));
    const apply = (data: T) => {
      if (!controller.signal.aborted) setState({ key, data, error: '', loading: false });
    };
    const fail = (error: unknown) => {
      if (controller.signal.aborted) return;
      const denied = error !== null && typeof error === 'object' && 'status' in error && [401, 403].includes(Number(error.status));
      // Authorization denial wins over both visible data and a late warm result.
      if (denied) controller.abort();
      setState((current) => ({ ...current, data: denied ? null : current.data, loading: false, error: error instanceof Error ? error.message : 'Unable to load CRM data.' }));
    };
    void read<T>(JSON.parse(key), {
      signal: controller.signal,
      onRevalidated: (data) => { revalidated = true; apply(data); },
      onRevalidationError: fail,
    }).then((data) => { if (!revalidated) apply(data); }).catch(fail);
    return () => controller.abort();
  }, [key, revision, read]);
  useEffect(() => {
    const changed = (event: MessageEvent) => {
      if (isExactMaverickParentMessage(event) && ['maverick.app.data-changed', 'maverick.widget.data-changed'].includes(event.data?.type) && event.data?.owner_app_id === 'crm') refresh();
    };
    window.addEventListener('message', changed);
    window.addEventListener('crm-workspace-refresh', refresh);
    return () => { window.removeEventListener('message', changed); window.removeEventListener('crm-workspace-refresh', refresh); };
  }, [refresh]);
  return { ...(state.key === key ? state : { data: null, error: '', loading: true }), refresh };
}
