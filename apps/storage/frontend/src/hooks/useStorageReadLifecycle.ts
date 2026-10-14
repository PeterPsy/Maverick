import { useEffect, useRef } from 'react';
import { loopinoAppIsVisible, observeLoopinoVisibility } from '@loopino/pwa-cache';
import { StorageCatalogRequests } from '../lib/storageCatalogRequests';

/** Suspends a Storage surface's reads, preserving its UI and any accepted mutations. */
export function useStorageReadLifecycle(onResume: () => void) {
  const requests = useRef(new StorageCatalogRequests()).current;
  const resume = useRef(onResume);
  resume.current = onResume;
  useEffect(() => {
    let visible = loopinoAppIsVisible();
    requests.setVisible(visible);
    const stop = observeLoopinoVisibility((next) => {
      if (next === visible) return;
      visible = next;
      requests.setVisible(next);
      if (next) resume.current();
    });
    return () => { requests.dispose(); stop(); };
  }, [requests]);
  return requests;
}
