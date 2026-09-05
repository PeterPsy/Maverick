import { displayRecord, projectDisplayModel, type DisplayModelSchema } from '@maverick/pwa-cache';
import schemas from '../../pwa_read_models.v1.json';

export type CrmReadModel = { kind: string; data: Record<string, unknown> };
export function sanitizeCrmReadModel(value: unknown): CrmReadModel | null {
  const model = displayRecord(value);
  if (!model || typeof model.kind !== 'string' || !Object.hasOwn(schemas, model.kind)) return null;
  const data = projectDisplayModel(model.data, (schemas as Record<string, DisplayModelSchema>)[model.kind]);
  return data ? { kind: model.kind, data } : null;
}
