import { readAppCacheModel, type AppReadModelOptions } from '@maverick/pwa-cache';
import { sanitizeCrmReadModel } from './pwaReadModel';
import { isPublicCrm } from './public/context';
import { readPublicDisplay } from './public/readDisplay';

export async function readCrmDisplay<T>(parameters: Record<string, unknown>, options: AppReadModelOptions<T> = {}): Promise<T> {
  if (isPublicCrm) {
    return readPublicDisplay<T>(parameters, options.signal);
  }
  const result = await readAppCacheModel({
    appId: 'crm', resource: 'lists-and-recent-records', schemaRevision: 'crm.lists-and-recent-records.v2', parameters,
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
