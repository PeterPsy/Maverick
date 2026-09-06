import type { PreviewPayload, WorkspaceSnapshot } from './api';

export function preview(version: string, route = '/'): PreviewPayload {
  const previewId = `preview-${version}-${route === '/' ? 'home' : 'about'}`;
  return {
    preview_id: previewId,
    site_id: 'site',
    environment_id: 'env_preview',
    route,
    runtime_kind: 'static',
    runtime_status: 'ready',
    preview_url: `/apps/website-studio/preview-runtime/?preview_id=${previewId}&route=${encodeURIComponent(route)}`,
    build_id: `build-${version}`,
    missing_requirements: [],
    warnings: [],
    html: ''
  };
}

export function snapshot(version: string, withPreview = true): WorkspaceSnapshot {
  const site = { id: 'site', display_name: 'Site', slug: 'site', status: 'draft', source_provider: 'git', is_active: true };
  const latest = preview(version);
  return {
    schema: 'workspace_snapshot.v1',
    revision: version.repeat(64),
    versions: {
      workspace_version: '1', project_version: '1', source_version: version,
      navigation_version: version, working_state_version: version,
      preview_version: version, activity_version: version, settings_version: '1'
    },
    workspace: { projects: [site], active_project_id: site.id, persisted_active_project_id: site.id },
    project: {
      site,
      navigation: {
        site_id: site.id, site,
        pages: [{ id: 'home', site_id: site.id, route: '/', title: 'Home', kind: 'html', status: 'active', source_files: [] }],
        routes: [{ id: 'about', site_id: site.id, route: '/about', kind: 'html', status: 'active', source_files: [] }],
        inventory_summary: { page_count: 1, route_count: 1, asset_count: 0 }
      },
      working_state: { changed_files_count: 0 }, activity: {},
      latest_preview: withPreview ? { ...latest, id: latest.preview_id } : null
    }
  };
}

export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((accept, fail) => { resolve = accept; reject = fail; });
  return { promise, resolve, reject };
}
