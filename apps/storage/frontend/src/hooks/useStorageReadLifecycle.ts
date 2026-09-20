import { useEffect, useRef } from 'react';
import { isExactMaverickParentMessage } from '@maverick/pwa-cache';
import { StorageCatalogRequests } from '../lib/storageCatalogRequests';

/** Suspends a Storage surface's reads, preserving its UI and any accepted mutations. */
export function useStorageReadLifecycle(onResume: () => void) {
  const requests = useRef(new StorageCatalogRequests()).current;
  const resume = useRef(onResume);
  resume.current = onResume;
  useEffect(() => {
    let shellVisible = true;
    let visible = !document.hidden && navigator.onLine;
    requests.setVisible(visible);
    function update() {
      const next = shellVisible && !document.hidden && navigator.onLine;
      if (next === visible) return;
      visible = next;
      requests.setVisible(next);
      if (next) resume.current();
    }
    function message(event: MessageEvent) {
      if (!isExactMaverickParentMessage(event)) return;
      if (event.data?.type !== 'maverick.app.visibility-changed') return;
      shellVisible = event.data.visible !== false;
      update();
    }
    document.addEventListener('visibilitychange', update);
    window.addEventListener('online', update);
    window.addEventListener('offline', update);
    window.addEventListener('message', message);
    return () => {
      requests.dispose();
      document.removeEventListener('visibilitychange', update);
      window.removeEventListener('online', update);
      window.removeEventListener('offline', update);
      window.removeEventListener('message', message);
    };
  }, [requests]);
  return requests;
}
