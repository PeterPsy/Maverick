import { useEffect } from 'react';
import { connectAppEventSocket } from '@maverick/pwa-cache';
import { broadcastMaverickFrameEvent, isShellWindowMessage, registeredMaverickFrameOwner, type MaverickFrameScope } from '../iframePolicy';
import runtimeResources from '../pwaDataCacheResourceDeclarations.v1.json';

type AppEvent = { type?: string; owner_app_id?: string; workspace_id?: string; frames_notified?: boolean };

/** The authenticated shell owns the stream even when only sidebar widgets are mounted. */
export function useShellAppEvents(scope: MaverickFrameScope | null) {
  useEffect(() => {
    if (!scope) return;
    const forward = (event: AppEvent) => {
      if (event.workspace_id && event.workspace_id !== scope.workspaceId) return;
      broadcastMaverickFrameEvent(scope, { type: 'maverick.app.event', event });
      if (event.type === 'maverick.app.data-changed') broadcastMaverickFrameEvent(scope, event);
      window.postMessage({ ...event, frames_notified: true }, window.location.origin);
    };
    const stop = connectAppEventSocket<AppEvent>(forward, () => {
      broadcastMaverickFrameEvent(scope, { type: 'maverick.app.events-resync' });
      for (const declaration of runtimeResources.resources) {
        const event = { type: 'maverick.app.data-changed', owner_app_id: declaration.app_id,
          resource: declaration.aliases[0] ?? declaration.resource, resync: true, workspace_id: scope.workspaceId };
        broadcastMaverickFrameEvent(scope, event);
        window.postMessage({ ...event, frames_notified: true }, window.location.origin);
      }
    });
    const onLocalChange = (event: MessageEvent) => {
      const payload = event.data as AppEvent | null;
      if (!payload || payload.type !== 'maverick.app.data-changed' || payload.frames_notified || !payload.owner_app_id) return;
      if (isShellWindowMessage(event) || registeredMaverickFrameOwner(event, scope) === payload.owner_app_id) forward(payload);
    };
    window.addEventListener('message', onLocalChange);
    return () => { stop(); window.removeEventListener('message', onLocalChange); };
  }, [scope]);
}
