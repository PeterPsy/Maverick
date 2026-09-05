import { readAppCacheModel, type AppReadModelOptions } from '@maverick/pwa-cache';
import { sanitizeCrmReadModel } from './pwaReadModel';

export async function readCrmDisplay<T>(parameters: Record<string, unknown>, options: AppReadModelOptions<T> = {}): Promise<T> {
  const result = await readAppCacheModel({
    appId: 'crm', resource: 'lists-and-recent-records', schemaRevision: 'crm.lists-and-recent-records.v1', parameters,
  }, (value) => {
    const model = sanitizeCrmReadModel(value);
    return model?.kind === parameters.kind ? model : null;
  }, {
    signal: options.signal,
    onRevalidated: (model) => options.onRevalidated?.(model.data as T),
    onRevalidationError: options.onRevalidationError,
  });
  return result.payload.data as T;
}
