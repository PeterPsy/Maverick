const CATALOG_SCHEMA = 'maverick.app-store-catalog.v1';
const REVISION_PATTERN = /^[a-f0-9]{64}$/u;
const FORBIDDEN_KEYS = new Set([
  'authorization',
  'credential',
  'credentials',
  'password',
  'signedurl',
  'token'
]);

export function sanitizeCatalog(value) {
  if (!isRecord(value)
      || value.schema !== CATALOG_SCHEMA
      || !REVISION_PATTERN.test(String(value.revision || ''))
      || !Array.isArray(value.items)) return null;
  try {
    const cloned = JSON.parse(JSON.stringify(value, (key, item) => {
      const normalized = key.replace(/[^A-Za-z0-9]/gu, '').toLowerCase();
      if (FORBIDDEN_KEYS.has(normalized)
          || normalized.endsWith('token')
          || normalized.endsWith('secret')) return undefined;
      if (typeof item === 'string'
          && (/^blob\s*:/iu.test(item)
            || /[?&](?:sig|signature|x-amz-signature|x-goog-signature)=/iu.test(item))) return undefined;
      return item;
    }));
    if (!isRecord(cloned)
        || !Array.isArray(cloned.items)
        || !cloned.items.every(validCatalogApp)) return null;
    return cloned;
  } catch {
    return null;
  }
}

function validCatalogApp(app) {
  return isRecord(app)
    && boundedString(app.app_id, 128)
    && boundedString(app.name, 512)
    && optionalStringArray(app.surfaces)
    && optionalRecord(app.presentation)
    && (app.versions === undefined
      || (Array.isArray(app.versions) && app.versions.every(validCatalogVersion)));
}

function validCatalogVersion(version) {
  return isRecord(version)
    && boundedString(version.version, 256)
    && optionalStringArray(version.surfaces)
    && optionalRecord(version.presentation);
}

function boundedString(value, maxLength) {
  return typeof value === 'string' && value.length > 0 && value.length <= maxLength;
}

function optionalStringArray(value) {
  return value === undefined
    || (Array.isArray(value) && value.every((item) => typeof item === 'string'));
}

function optionalRecord(value) {
  return value === undefined || isRecord(value);
}

function isRecord(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}
