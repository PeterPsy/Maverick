import { readAppCacheModel, type AppReadModelOptions } from '@maverick/pwa-cache';
import { sanitizeMailReadModel } from './pwaReadModel';

export async function readMailDisplay<T>(parameters: Record<string, unknown>, options: AppReadModelOptions<T> = {}): Promise<T> {
  const result = await readAppCacheModel({
    appId: 'mail', resource: 'thread-headers-snippets-and-bodies', schemaRevision: 'mail.thread-headers-snippets-and-bodies.v1', parameters,
  }, (value) => {
    const model = sanitizeMailReadModel(value);
    return model?.kind === parameters.kind ? model : null;
  }, {
    signal: options.signal,
    onRevalidated: (model) => options.onRevalidated?.(model.data as T),
    onRevalidationError: options.onRevalidationError,
  });
  return result.payload.data as T;
}
