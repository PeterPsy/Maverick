import { useEffect, useMemo, useRef, useState } from 'react';
import type { DragEvent } from 'react';
import { callBackend, callStorageProvider, type Asset, type Page, type PreviewPayload, type Route, type SitemapPayload, type Site, type StorageFile } from './api';

type Notice = { tone: 'ok' | 'warn' | 'error'; text: string } | null;

export function App() {
  const [sites, setSites] = useState<Site[]>([]);
  const [activeSiteId, setActiveSiteId] = useState('');
  const [pages, setPages] = useState<Page[]>([]);
  const [activePageId, setActivePageId] = useState('');
  const [activeRouteId, setActiveRouteId] = useState('');
  const [activeAssetId, setActiveAssetId] = useState('');
  const [previewHtml, setPreviewHtml] = useState('');
  const [previewState, setPreviewState] = useState<PreviewPayload | null>(null);
  const [showNewWebsite, setShowNewWebsite] = useState(false);
  const [gitDialogOpen, setGitDialogOpen] = useState(false);
  const [gitUrl, setGitUrl] = useState('');
  const [gitBranch, setGitBranch] = useState('');
  const [notice, setNotice] = useState<Notice>(null);
  const [busy, setBusy] = useState(false);
  const [draggingZip, setDraggingZip] = useState(false);
  const activeSiteIdRef = useRef('');
  const activePageIdRef = useRef('');

  const activeSite = useMemo(() => sites.find((site) => site.id === activeSiteId), [sites, activeSiteId]);
  const activePage = useMemo(() => pages.find((page) => page.id === activePageId), [pages, activePageId]);
  const importOnly = showNewWebsite || !activeSite;
  const previewUrl = previewState?.preview_url || '';

  useEffect(() => {
    activeSiteIdRef.current = activeSiteId;
  }, [activeSiteId]);

  useEffect(() => {
    activePageIdRef.current = activePageId;
  }, [activePageId]);

  async function refresh(nextSiteId = activeSiteIdRef.current, nextPageId = activePageIdRef.current, nextRoute = '', nextRouteId = '', nextAssetId = '') {
    const sitePayload = await callBackend<{ items: Site[] }>({ action: 'sites_list' });
    setSites(sitePayload.items);
    const availableSites = sitePayload.items.filter((site) => site.status !== 'archived');
    const requestedSite = availableSites.find((site) => site.id === nextSiteId)?.id || '';
    const persistedSite = availableSites.find((site) => site.is_active)?.id || '';
    const selectedSite = requestedSite || persistedSite || availableSites[0]?.id || '';
    setActiveSiteId(selectedSite);
    if (!selectedSite) {
      setPages([]);
      setActivePageId('');
      setActiveRouteId('');
      setActiveAssetId('');
      setPreviewHtml('');
      setPreviewState(null);
      setShowNewWebsite(true);
      return;
    }
    if (selectedSite !== persistedSite) {
      await callBackend({ action: 'site_set_active', site_id: selectedSite });
    }

    const map = await callBackend<SitemapPayload>({ action: 'sitemap', site_id: selectedSite });
    setPages(map.items);
    const selectedRoute = (map.routes || []).find((route) => route.id === nextRouteId) || (map.routes || []).find((route) => route.route === nextRoute);
    const selectedAsset = (map.assets || []).find((asset) => asset.id === nextAssetId);
    const selectedPage =
      map.items.find((page) => page.id === nextPageId) ||
      (selectedRoute?.page_id ? map.items.find((page) => page.id === selectedRoute.page_id) : undefined) ||
      map.items.find((page) => page.route === nextRoute) ||
      (selectedRoute && !selectedRoute.page_id ? undefined : map.items[0]);
    setActivePageId(selectedPage?.id || '');
    setActiveRouteId(selectedRoute?.id || '');
    setActiveAssetId(selectedAsset?.id || '');
    const previewRoute = selectedPage?.route || selectedRoute?.route || '/';
    postSelection(selectedSite, selectedPage, selectedRoute, selectedAsset);
    await renderSite(selectedSite, previewRoute);
  }

  async function renderSite(siteId: string, route = '/') {
    const payload = await callBackend<PreviewPayload>({ action: 'build_preview', site_id: siteId, route });
    setPreviewState(payload);
    setPreviewHtml(payload.html || '');
  }

  useEffect(() => {
    refresh().catch((error: Error) => setNotice({ tone: 'error', text: error.message }));
  }, []);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') return;
      const payload = event.data as { type?: string; params?: Record<string, string> };
      if (payload.type === 'maverick.app.data-changed' && (payload as { owner_app_id?: string }).owner_app_id === 'website-studio') {
        refresh(activeSiteIdRef.current, activePageIdRef.current).catch((error: Error) => setNotice({ tone: 'error', text: error.message }));
        return;
      }
      if (payload.type !== 'maverick.app.navigate') return;
      if (payload.params?.new_website_request_id) {
        setShowNewWebsite(true);
        setNotice(null);
        return;
      }
      const appPage = (payload.params?.app_page || '').replace(/^\/+|\/+$/g, '');
      const pageFromRoute = appPage.startsWith('pages/') ? appPage.slice('pages/'.length) : '';
      const routeFromRoute = appPage.startsWith('routes/') ? appPage.slice('routes/'.length) : '';
      const assetFromRoute = appPage.startsWith('assets/') ? appPage.slice('assets/'.length) : '';
      if (payload.params?.site_id || pageFromRoute || routeFromRoute || assetFromRoute || payload.params?.route) {
        setShowNewWebsite(false);
        refresh(
          payload.params?.site_id || activeSiteIdRef.current,
          payload.params?.page_id || pageFromRoute,
          payload.params?.route || '',
          payload.params?.route_id || routeFromRoute,
          payload.params?.asset_id || assetFromRoute
        ).catch((error: Error) => setNotice({ tone: 'error', text: error.message }));
      }
    }
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  async function run<T>(fn: () => Promise<T>, message?: string) {
    setBusy(true);
    setNotice(null);
    try {
      const result = await fn();
      if (message) setNotice({ tone: 'ok', text: message });
      return result;
    } catch (error) {
      setNotice({ tone: 'error', text: error instanceof Error ? error.message : String(error) });
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  async function importZip(fileInput: File | null) {
    if (!fileInput) return;
    if (!fileInput.name.toLowerCase().endsWith('.zip')) {
      setNotice({ tone: 'warn', text: 'Select a ZIP archive.' });
      return;
    }
    const encoded = await toBase64(fileInput);
    const displayName = fileInput.name.replace(/\.zip$/i, '').replace(/[-_]+/g, ' ').trim() || 'Imported Website';
    const payload = await run(
      async () => {
        const stored = await writeZipToStorage(fileInput, encoded);
        return callBackend<{ site: Site }>({
          action: 'import_zip',
          display_name: displayName,
          archive_base64: encoded,
          source_artifact_ref: storageArtifactRef(stored.file, fileInput)
        });
      },
      'ZIP imported'
    );
    if (payload?.site) {
      setShowNewWebsite(false);
      await refresh(payload.site.id);
    }
  }

  function handleZipDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDraggingZip(false);
    if (busy) return;
    const file = Array.from(event.dataTransfer.files).find((item) => item.name.toLowerCase().endsWith('.zip'));
    if (!file) {
      setNotice({ tone: 'warn', text: 'Drop a ZIP archive.' });
      return;
    }
    void importZip(file);
  }

  async function importGit() {
    const repositoryUrl = gitUrl.trim();
    const baseBranch = gitBranch.trim() || undefined;
    if (!repositoryUrl) {
      setNotice({ tone: 'warn', text: 'Repository URL is required.' });
      return;
    }
    const payload = await run(
      async () => {
        const prepared = await callBackend<{ site: Site }>({
          action: 'git_connection_prepare',
          repository_url: repositoryUrl,
          base_branch: baseBranch,
          auth_mode: 'fine_grained_token'
        });
        return callBackend<{ site: Site }>({
          action: 'import_git',
          site_id: prepared.site.id,
          repository_url: repositoryUrl,
          branch: baseBranch
        });
      },
      'Git connected and imported'
    );
    if (payload?.site) {
      setGitDialogOpen(false);
      setShowNewWebsite(false);
      setGitUrl('');
      setGitBranch('');
      await refresh(payload.site.id);
    }
  }

  return (
    <main className={importOnly ? 'website-studio-shell import-mode' : 'website-studio-shell site-mode'}>
      {notice ? <div className={`notice ${notice.tone}`}>{notice.text}</div> : null}

      {importOnly ? (
        <section className="import-screen" aria-label="New website">
          <div className="import-actions">
            <label
              className={`import-button drop-target${draggingZip ? ' dragging' : ''}`}
              onDragEnter={(event) => {
                event.preventDefault();
                if (!busy) setDraggingZip(true);
              }}
              onDragOver={(event) => {
                event.preventDefault();
                if (!busy) event.dataTransfer.dropEffect = 'copy';
              }}
              onDragLeave={() => setDraggingZip(false)}
              onDrop={handleZipDrop}
              aria-disabled={busy}
            >
              <span className="import-button-icon" aria-hidden="true">upload_file</span>
              <span>Drop ZIP</span>
              <input type="file" accept=".zip,application/zip" onChange={(event) => importZip(event.target.files?.[0] || null)} disabled={busy} />
            </label>
            <button className="import-button" onClick={() => setGitDialogOpen(true)} disabled={busy}>
              <span className="import-button-icon" aria-hidden="true">commit</span>
              <span>Connect Git</span>
            </button>
          </div>
          {gitDialogOpen ? (
            <form
              className="git-import"
              onSubmit={(event) => {
                event.preventDefault();
                void importGit();
              }}
            >
              <input
                value={gitUrl}
                onChange={(event) => setGitUrl(event.target.value)}
                placeholder="https://github.com/company/site.git"
                autoComplete="off"
                disabled={busy}
              />
              <input
                value={gitBranch}
                onChange={(event) => setGitBranch(event.target.value)}
                placeholder="base branch"
                autoComplete="off"
                disabled={busy}
              />
              <div className="git-import-actions">
                <button type="button" onClick={() => setGitDialogOpen(false)} disabled={busy}>Cancel</button>
                <button type="submit" disabled={busy}>Connect</button>
              </div>
            </form>
          ) : null}
        </section>
      ) : (
        <section className="site-canvas" aria-label={activeSite?.display_name || 'Website'}>
          {previewHtml ? (
            <>
              {previewUrl ? (
                <iframe
                  title={activePage?.title || activeSite?.display_name || 'Website preview'}
                  data-route-id={activeRouteId}
                  data-asset-id={activeAssetId}
                  sandbox="allow-scripts allow-same-origin"
                  src={previewUrl}
                />
              ) : (
                <iframe
                  title={activePage?.title || activeSite?.display_name || 'Website preview'}
                  data-route-id={activeRouteId}
                  data-asset-id={activeAssetId}
                  sandbox=""
                  srcDoc={previewHtml}
                />
              )}
              {previewState ? <PreviewStatus preview={previewState} /> : null}
            </>
          ) : (
            <div className="site-empty">No renderable page in this site.</div>
          )}
        </section>
      )}
    </main>
  );
}

function PreviewStatus({ preview }: { preview: PreviewPayload }) {
  const requirements = preview.missing_requirements || [];
  const warnings = preview.warnings || [];
  const detail = requirements[0] || warnings[0] || '';
  return (
    <div className="preview-status" data-runtime-kind={preview.runtime_kind} data-runtime-status={preview.runtime_status}>
      <i aria-hidden="true" />
      <span>{preview.runtime_kind.replace('_', ' ')}</span>
      <strong>{preview.runtime_status.replace('_', ' ')}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

function postSelection(siteId: string, page?: Page, route?: Route, asset?: Asset) {
  if (!siteId) return;
  const appPage = asset ? `assets/${asset.id}` : route ? `routes/${route.id}` : page ? `pages/${page.id}` : `sites/${siteId}`;
  const activeView = asset ? 'asset' : route && !page ? 'route' : page ? 'page' : 'site';
  window.parent?.postMessage(
    {
      type: 'maverick.app.selection-changed',
      app_id: 'website-studio',
      owner_app_id: 'website-studio',
      params: {
        site_id: siteId,
        active_view: activeView,
        page_id: page?.id || '',
        route_id: route?.id || '',
        asset_id: asset?.id || '',
        route: page?.route || route?.route || '',
        title: page?.title || route?.route || asset?.path || '',
        context_tool: 'website_page_context',
        app_page: appPage
      }
    },
    window.location.origin
  );
}

async function writeZipToStorage(file: File, contentBase64: string): Promise<{ file?: StorageFile }> {
  const safeName = file.name.replace(/[^A-Za-z0-9_.-]+/g, '-').replace(/^-+|-+$/g, '') || 'website.zip';
  return callStorageProvider<{ file?: StorageFile }>('storage-writer', {
    action: 'file.content.write',
    workspace_relative_path: `storage/uploaded/website-studio/${Date.now()}-${safeName}`,
    mode: 'create',
    content_base64: contentBase64,
    content_type: file.type || 'application/zip'
  });
}

function storageArtifactRef(file: StorageFile | undefined, fallback: File): Record<string, string> {
  return {
    app_id: 'storage',
    file_id: file?.file_id || file?.id || '',
    workspace_relative_path: file?.workspace_relative_path || '',
    role: file?.role || 'uploaded',
    relative_path: file?.relative_path || '',
    name: file?.name || fallback.name,
    content_type: file?.content_type || fallback.type || 'application/zip',
    sha256: file?.sha256 || ''
  };
}

async function toBase64(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  let binary = '';
  for (const byte of new Uint8Array(buffer)) binary += String.fromCharCode(byte);
  return btoa(binary);
}
