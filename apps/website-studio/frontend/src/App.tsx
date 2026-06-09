import { useEffect, useMemo, useRef, useState } from 'react';
import {
  callBackend,
  type Asset,
  type ChangeHistoryPayload,
  type ChangeRecord,
  type Page,
  type PreviewPayload,
  type Route,
  type SitemapPayload,
  type Site,
  type SiteStatusPayload
} from './api';

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
  const [previewLoading, setPreviewLoading] = useState(false);
  const [siteStatus, setSiteStatus] = useState<SiteStatusPayload | null>(null);
  const [changeHistory, setChangeHistory] = useState<ChangeHistoryPayload | null>(null);
  const [showNewWebsite, setShowNewWebsite] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [infoPanelOpen, setInfoPanelOpen] = useState(false);
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
      setPreviewLoading(false);
      setSiteStatus(null);
      setChangeHistory(null);
      setShowNewWebsite(true);
      setInfoPanelOpen(false);
      return;
    }
    setPreviewLoading(true);
    setPreviewHtml('');
    setPreviewState(null);
    try {
      if (selectedSite !== persistedSite) {
        await callBackend({ action: 'site_set_active', site_id: selectedSite });
      }

      const map = await callBackend<SitemapPayload>({ action: 'sitemap', site_id: selectedSite });
      const [statusPayload, changesPayload] = await Promise.all([
        callBackend<SiteStatusPayload>({ action: 'site_status', site_id: selectedSite }),
        callBackend<ChangeHistoryPayload>({ action: 'list_changes', site_id: selectedSite })
      ]);
      setSiteStatus(statusPayload);
      setChangeHistory(changesPayload);
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
      await renderSite(selectedSite, previewRoute, statusPayload);
    } finally {
      setPreviewLoading(false);
    }
  }

  async function renderSite(siteId: string, route = '/', status?: SiteStatusPayload) {
    const latestPreview = status?.runtime?.latest_preview || null;
    if (latestPreview?.id && latestPreview.route === route && latestPreview.preview_url) {
      try {
        const document = await callBackend<PreviewDocumentPayload>({ action: 'preview_document', preview_id: latestPreview.id });
        const payload = previewPayloadFromDocument(siteId, route, document);
        setPreviewState(payload);
        setPreviewHtml(payload.html || ' ');
        return;
      } catch {
        // Fall through to creating a fresh preview when the cached document is stale.
      }
    }
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
        setInfoPanelOpen(false);
        setNotice(null);
        return;
      }
      const appPage = (payload.params?.app_page || '').replace(/^\/+|\/+$/g, '');
      const wantsInfoPanel =
        payload.params?.website_info === '1' ||
        payload.params?.info_panel === '1' ||
        appPage === 'info' ||
        appPage === 'site/info';
      const pageFromRoute = appPage.startsWith('pages/') ? appPage.slice('pages/'.length) : '';
      const routeFromRoute = appPage.startsWith('routes/') ? appPage.slice('routes/'.length) : '';
      const assetFromRoute = appPage.startsWith('assets/') ? appPage.slice('assets/'.length) : '';
      if (wantsInfoPanel) {
        setShowNewWebsite(false);
        setInfoPanelOpen(true);
        refresh(
          payload.params?.site_id || activeSiteIdRef.current,
          payload.params?.page_id || pageFromRoute || activePageIdRef.current,
          payload.params?.route || '',
          payload.params?.route_id || routeFromRoute,
          payload.params?.asset_id || assetFromRoute
        ).catch((error: Error) => setNotice({ tone: 'error', text: error.message }));
        return;
      }
      if (payload.params?.site_id || pageFromRoute || routeFromRoute || assetFromRoute || payload.params?.route) {
        setShowNewWebsite(false);
        setInfoPanelOpen(false);
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

  return (
    <main className={importOnly ? 'website-studio-shell import-mode' : 'website-studio-shell site-mode'}>
      {notice ? <div className={`notice ${notice.tone}`}>{notice.text}</div> : null}

      {importOnly ? (
        <section className="connection-guide" aria-label="Connect a website">
          <span className="connection-guide-kicker">Website Studio</span>
          <h1>Scrivi in chat a un agente che vuoi connettere un sito.</h1>
          <p>
            L'agente ti guidera passo passo: puoi incollare un link ZIP di Drive, oppure collegare una repository GitHub
            usando un secret salvato in Vault. Buon divertimento.
          </p>
          <div className="connection-guide-options" aria-label="Connection options">
            <span>ZIP da Drive</span>
            <span>GitHub con Vault</span>
          </div>
        </section>
      ) : (
        <section className="site-canvas" aria-label={activeSite?.display_name || 'Website'}>
          {previewLoading ? (
            <PreviewLoadingState />
          ) : previewUrl || previewHtml ? (
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
              {infoPanelOpen && previewState && siteStatus ? (
                <WebsiteInfoPanel
                  preview={previewState}
                  status={siteStatus}
                  changes={changeHistory}
                  site={activeSite}
                  onClose={() => setInfoPanelOpen(false)}
                />
              ) : null}
            </>
          ) : (
            <div className="site-empty">No renderable page in this site.</div>
          )}
        </section>
      )}
    </main>
  );
}

function PreviewLoadingState() {
  return (
    <div className="preview-loading-state" role="status" aria-label="Preview is loading">
      <span className="preview-loading-indicator" aria-hidden="true">
        <span className="preview-loading-shape" />
      </span>
      <span className="preview-loading-label">Preview is loading</span>
    </div>
  );
}

function WebsiteInfoPanel({
  preview,
  status,
  changes,
  site,
  onClose
}: {
  preview: PreviewPayload;
  status: SiteStatusPayload;
  changes: ChangeHistoryPayload | null;
  site?: Site;
  onClose: () => void;
}) {
  const latestBuild = latest(changes?.builds) || status.runtime?.latest_build || null;
  const latestRequest = latest(changes?.publish_requests);
  const latestDeploy = latest(changes?.deployments);
  const pendingRequests = (changes?.publish_requests || []).filter((item) => item.status === 'pending').length;
  const deployed = latestDeploy?.status || (site?.published_revision_id ? 'published' : 'not published');
  const requirements = preview.missing_requirements || [];
  const warnings = preview.warnings || [];
  const runtimeDetail = requirements[0] || warnings[0] || 'Preview runtime ready.';
  const runtimeKind = preview.runtime_kind || status.runtime_kind || status.runtime?.runtime_kind || 'preview';
  const runtimeStatus = preview.runtime_status || status.runtime_status || status.runtime?.runtime_status || 'unknown';
  return (
    <aside className="website-info-panel" aria-label="Website info">
      <div className="website-info-header">
        <div className="website-info-title">
          <span>site info</span>
          <strong>{site?.display_name || status.site.display_name}</strong>
        </div>
        <button className="website-info-close" type="button" aria-label="Close info" onClick={onClose}>
          <span aria-hidden="true" />
        </button>
      </div>

      <div className="website-info-runtime" data-runtime-status={runtimeStatus}>
        <i aria-hidden="true" />
        <div>
          <span>{String(runtimeKind).replace('_', ' ')}</span>
          <strong>{String(runtimeStatus).replace('_', ' ')}</strong>
          <small>{runtimeDetail}</small>
        </div>
      </div>

      <div className="website-info-metrics">
        <Metric label="pages" value={status.page_count} />
        <Metric label="routes" value={status.route_count} />
        <Metric label="assets" value={status.asset_count} />
        <Metric label="changed" value={status.changed_files_count} tone={status.changed_files_count ? 'warn' : 'ok'} />
      </div>

      <div className="website-info-lines">
        <InfoLine label="runtime" value={String(status.runtime_status || status.runtime?.runtime_status || 'unknown').replace('_', ' ')} />
        <InfoLine label="build" value={String(latestBuild?.status || 'none').replace('_', ' ')} />
        <InfoLine label="requests" value={pendingRequests ? `${pendingRequests} pending` : String(latestRequest?.status || 'none').replace('_', ' ')} />
        <InfoLine label="deploys" value={String(deployed).replace('_', ' ')} />
      </div>
    </aside>
  );
}

function latest(records?: ChangeRecord[] | null): ChangeRecord | null {
  return records && records.length ? records[0] : null;
}

function Metric({ label, value, tone = 'neutral' }: { label: string; value: number; tone?: 'neutral' | 'ok' | 'warn' }) {
  return (
    <div className="website-info-metric" data-tone={tone}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function InfoLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="website-info-line">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

type PreviewDocumentPayload = {
  preview?: Partial<PreviewPayload> & {
    id?: string;
    status?: string;
    warnings?: string[];
    missing_requirements?: string[];
  };
  html?: string;
};

function previewPayloadFromDocument(siteId: string, route: string, document: PreviewDocumentPayload): PreviewPayload {
  const preview = document.preview || {};
  return {
    preview_id: String(preview.preview_id || preview.id || ''),
    site_id: String(preview.site_id || siteId),
    environment_id: String(preview.environment_id || 'env_preview'),
    route: String(preview.route || route || '/'),
    page_id: String(preview.page_id || ''),
    route_id: String(preview.route_id || ''),
    runtime_kind: String(preview.runtime_kind || 'unavailable'),
    runtime_status: String(preview.runtime_status || preview.status || 'unknown'),
    preview_url: String(preview.preview_url || ''),
    build_id: String(preview.build_id || ''),
    missing_requirements: Array.isArray(preview.missing_requirements) ? preview.missing_requirements : [],
    warnings: Array.isArray(preview.warnings) ? preview.warnings : [],
    html: String(document.html || '')
  };
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
