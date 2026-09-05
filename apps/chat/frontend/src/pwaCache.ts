import { readAppCacheModel, type AppReadModelOptions } from '@maverick/pwa-cache';
import { sanitizeChatReadModel } from './pwaReadModel';

export async function readChatDisplay<T>(parameters: Record<string, unknown>, options: AppReadModelOptions<T> = {}): Promise<T> {
  const result = await readAppCacheModel({
    appId: 'chat', resource: 'projects-and-completed-messages', schemaRevision: 'chat.projects-and-completed-messages.v1', parameters,
  }, (value) => {
    const model = sanitizeChatReadModel(value);
    return model?.kind === parameters.kind ? model : null;
  }, {
    signal: options.signal,
    onRevalidated: (model) => options.onRevalidated?.(model.data as T),
    onRevalidationError: options.onRevalidationError,
  });
  return result.payload.data as T;
}

// Only a RAM rendering bridge. These events never grant session/turn authority and
// are replaced, not merged, when the first authoritative stream snapshot arrives.
export type CompletedDisplayMessage = { id: string; turn_id: string; role: 'user' | 'assistant'; text: string; created_at: string };
export function displayMessageEvents(sessionId: string, messages: CompletedDisplayMessage[]): import('./api/client').RuntimeEvent[] {
  return messages.flatMap((message) => {
    const event = { session_id: sessionId, turn_id: message.turn_id, created_at: message.created_at,
      event_id: `display:${message.id}`, event_type: message.role === 'user' ? 'runtime.turn.queued' : 'runtime.output.final',
      payload: message.role === 'user' ? { input_text: message.text } : { text: message.text },
    };
    return message.role === 'user' ? [event] : [event, { ...event, event_id: `${event.event_id}:complete`, event_type: 'runtime.turn.completed', payload: {} }];
  });
}
export function displayThread(value: Record<string, unknown>): import('./api/client').ChatThread {
  return { ...value, agent_type_id: '', agent_role_id: '', availability: 'unknown' } as import('./api/client').ChatThread;
}

export function invalidateChatDisplay(resource: 'runtime-threads' | 'messages'): void {
  const origin = (window as Window & { __MAVERICK_PLATFORM_ORIGIN__?: string }).__MAVERICK_PLATFORM_ORIGIN__;
  if (!origin || window.parent === window) return;
  window.parent.postMessage({ type: 'maverick.app.data-changed', owner_app_id: 'chat', resource }, origin);
}
