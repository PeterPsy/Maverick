// Catalog summaries omit mounted assets. Use the active workspace registry's
// public identity so Store and shell share an app-owned icon, including forks.
export function withRegistryLogo(app, registry = []) {
  if (app?.logo || !Array.isArray(registry)) return app;
  const identity = app?.public_app_id || app?.app_id;
  const mounted = registry.find(item => (item.public_app_id || item.app_id) === identity);
  return mounted?.logo ? { ...app, logo: mounted.logo } : app;
}
