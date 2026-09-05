import { displayRecord } from './readModelProjection';

export type DisplayModelSchema = {
  fields?: Record<string, string>;
  objects?: Record<string, DisplayModelSchema>;
  lists?: Record<string, DisplayModelSchema>;
  maps?: Record<string, string>;
  required?: string[];
};
const unsafeUrl = /^blob\s*:|[?&](?:sig|signature|x-amz-signature|x-goog-signature)=/iu;
const forbiddenKey = /password|secret|token|credential|authorization|authority|capabilit/iu;

/** Same closed schema is read by the app backend and the host cache broker. */
export function projectDisplayModel(value: unknown, schema: DisplayModelSchema, depth = 0): Record<string, unknown> | null {
  const raw = displayRecord(value);
  if (!raw || depth > 16) return null;
  if (schema.required?.some((key) => raw[key] === undefined || raw[key] === null)) return null;
  const result: Record<string, unknown> = {};
  for (const [field, kind] of Object.entries(schema.fields ?? {})) {
    const item = raw[field];
    if (item === undefined) { if (schema.required?.includes(field)) return null; continue; }
    if (item === null) { result[field] = null; continue; }
    if (kind === 'strings' ? !Array.isArray(item) || !item.every((entry) => typeof entry === 'string')
      : typeof item !== kind || (kind === 'number' && !Number.isFinite(item))) return null;
    if (typeof item === 'string' && unsafeUrl.test(item)) continue;
    result[field] = item;
  }
  for (const [field, shape] of Object.entries(schema.objects ?? {})) {
    if (raw[field] === undefined) continue;
    if (raw[field] === null) { result[field] = null; continue; }
    const child = projectDisplayModel(raw[field], shape, depth + 1);
    if (!child) return null;
    result[field] = child;
  }
  for (const [field, shape] of Object.entries(schema.lists ?? {})) {
    const values = raw[field];
    if (values === undefined) { if (schema.required?.includes(field)) return null; continue; }
    if (!Array.isArray(values)) return null;
    const children = values.map((item) => projectDisplayModel(item, shape, depth + 1));
    if (children.some((item) => !item)) return null;
    result[field] = children;
  }
  for (const [field, kind] of Object.entries(schema.maps ?? {})) {
    if (raw[field] === undefined) continue;
    const map = displayRecord(raw[field]);
    if (!map) return null;
    const entries: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(map)) {
      if (forbiddenKey.test(key) || ['__proto__', 'constructor', 'prototype'].includes(key)) continue;
      const scalar = item === null || typeof item === 'string' || typeof item === 'boolean' || (typeof item === 'number' && Number.isFinite(item));
      if (!scalar && !(kind === 'scalar' && Array.isArray(item) && item.every((entry) => typeof entry === 'string'))) return null;
      if (kind === 'number' && (typeof item !== 'number' || !Number.isFinite(item))) return null;
      if (typeof item === 'string' && unsafeUrl.test(item)) continue;
      entries[key] = item;
    }
    result[field] = entries;
  }
  return result;
}
