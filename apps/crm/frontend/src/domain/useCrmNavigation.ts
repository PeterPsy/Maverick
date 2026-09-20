import { useEffect, useRef, useState } from 'react';
import { postToShell } from './shellMessaging';
import { ViewId } from './types';
import { isPublicCrm } from '../public/context';
import { viewFromAppPage } from './routing';

/** Keep the shell's sole sidebar in sync with in-canvas navigation as well. */
export function useCrmNavigation() {
  const [view, applyShellView] = useState<ViewId>(() => isPublicCrm ? viewFromAppPage(location.hash.slice(1)).view : 'overview');
  const pending = useRef(new Set<string>());
  useEffect(() => {
    if (!isPublicCrm) return;
    const navigate = () => applyShellView(viewFromAppPage(location.hash.slice(1)).view);
    window.addEventListener('hashchange', navigate);
    return () => window.removeEventListener('hashchange', navigate);
  }, []);

  function setView(page: ViewId) {
    applyShellView(page);
    if (isPublicCrm) { location.hash = page; return; }
    const requestId = crypto.randomUUID();
    pending.current.add(requestId);
    if (!postToShell({ type: 'maverick.app.open-app', app_id: 'crm', params: { app_page: page, crm_navigation_id: requestId } })) {
      pending.current.delete(requestId);
    }
    // Navigation can be superseded before delivery. Never retain an unbounded log.
    if (pending.current.size > 32) pending.current.delete(pending.current.values().next().value!);
  }

  function consumeNavigationEcho(params: Record<string, unknown>) {
    const id = params.crm_navigation_id;
    // The reflected route updates the widget, not local filters, selection or forms.
    // Consuming once means revisiting that URL later still performs real navigation.
    return typeof id === 'string' && pending.current.delete(id);
  }

  return { view, setView, applyShellView, consumeNavigationEcho };
}
