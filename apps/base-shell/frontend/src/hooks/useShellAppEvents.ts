import { useEffect } from 'react';
import { connectAppEventSocket } from '@loopino/pwa-cache';
import { broadcastLoopinoFrameEvent, isShellWindowMessage, registeredLoopinoFrameOwner, type LoopinoFrameScope } from '../iframePolicy';
import runtimeResources from '../pwaDataCacheResourceDeclarations.v1.json';

type AppEvent = { type?: string; owner_app_id?: string; workspace_id?: string; frames_notified?: boolean };

/** The authenticated shell owns the stream even when only sidebar widgets are mounted. */
export function useShellAppEvents(scope: LoopinoFrameScope | null) {
  useEffect(() => {
    if (!scope) return;
    const forward = (event: AppEvent) => {
      if (event.workspace_id && event.workspace_id !== scope.workspaceId) return;
      broadcastLoopinoFrameEvent(scope, { type: 'loopino.app.event', event });
      if (event.type === 'loopino.app.data-changed') broadcastLoopinoFrameEvent(scope, event);
      window.postMessage({ ...event, frames_notified: true }, window.location.origin);
    };
    const stop = connectAppEventSocket<AppEvent>(forward, () => {
      broadcastLoopinoFrameEvent(scope, { type: 'loopino.app.events-resync' });
      for (const declaration of runtimeResources.resources) {
        const event = { type: 'loopino.app.data-changed', owner_app_id: declaration.app_id,
          resource: declaration.aliases[0] ?? declaration.resource, resync: true, workspace_id: scope.workspaceId };
        broadcastLoopinoFrameEvent(scope, event);
        window.postMessage({ ...event, frames_notified: true }, window.location.origin);
      }
    });
    const onLocalChange = (event: MessageEvent) => {
      const payload = event.data as AppEvent | null;
      if (!payload || payload.type !== 'loopino.app.data-changed' || payload.frames_notified || !payload.owner_app_id) return;
      if (isShellWindowMessage(event) || registeredLoopinoFrameOwner(event, scope) === payload.owner_app_id) forward(payload);
    };
    window.addEventListener('message', onLocalChange);
    return () => { stop(); window.removeEventListener('message', onLocalChange); };
  }, [scope]);
}
