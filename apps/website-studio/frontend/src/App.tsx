import { useEffect, useMemo, useRef, useState } from 'react';
import {
  callBackend,
  type Asset,
  type BootstrapPayload,
  type ChangeHistoryPayload,
  type ChangeRecord,
  type Page,
  type PreviewPayload,
  type Route,
  type RuntimeSummary,
  type Site,
  type SiteStatusPayload
} from './api';

type Notice = { tone: 'ok' | 'warn' | 'error'; text: string } | null;
type ActiveTarget = { anchor?: string; componentId?: string; id?: string; kind?: string; selector?: string };

const PREVIEW_RUNTIME_VERSION = 'preview-browser-stream-v4';
const PREVIEW_CLIENT_VERSION = 'website-studio-preview-frame-v7';

export function App() {
  const [sites, setSites] = useState<Site[]>([]);
  const [activeSiteId, setActiveSiteId] = useState('');
  const [pages, setPages] = useState<Page[]>([]);
  const [activePageId, setActivePageId] = useState('');
  const [activeRouteId, setActiveRouteId] = useState('');
  const [activeAssetId, setActiveAssetId] = useState('');
  const [activeTarget, setActiveTarget] = useState<ActiveTarget>({});
  const [previewHtml, setPreviewHtml] = useState('');
  const [previewState, setPreviewState] = useState<PreviewPayload | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [siteStatus, setSiteStatus] = useState<SiteStatusPayload | null>(null);
  const [changeHistory, setChangeHistory] = useState<ChangeHistoryPayload | null>(null);
  const [showNewWebsite, setShowNewWebsite] = useState(true);
  const [notice, setNotice] = useState<Notice>(null);
  const [infoPanelOpen, setInfoPanelOpen] = useState(false);
  const activeSiteIdRef = useRef('');
  const activePageIdRef = useRef('');
  const refreshRunRef = useRef(0);

  const activeSite = useMemo(() => sites.find((site) => site.id === activeSiteId), [sites, activeSiteId]);
  const activePage = useMemo(() => pages.find((page) => page.id === activePageId), [pages, activePageId]);
  const importOnly = showNewWebsite || !activeSite;
  const previewUrl = useMemo(() => normalizePreviewUrl(previewState?.preview_url || '', activeTarget), [activeTarget, previewState?.preview_url]);

  useEffect(() => {
    activeSiteIdRef.current = activeSiteId;
  }, [activeSiteId]);

  useEffect(() => {
    activePageIdRef.current = activePageId;
  }, [activePageId]);

  async function refresh(
    nextSiteId = activeSiteIdRef.current,
    nextPageId = activePageIdRef.current,
    nextRoute = '',
    nextRouteId = '',
    nextAssetId = '',
    nextTarget: ActiveTarget = {}
  ) {
    const runId = ++refreshRunRef.current;
    setPreviewLoading(true);
    setPreviewHtml('');
    setPreviewState(null);
    setSiteStatus(null);
    setChangeHistory(null);
    try {
      const bootstrap = await callBackend<BootstrapPayload>({
        action: 'bootstrap',
        site_id: nextSiteId || undefined,
        route: nextRoute || undefined
      });
      if (runId !== refreshRunRef.current) return;
      setSites(bootstrap.sites);
      const availableSites = bootstrap.sites.filter((site) => site.status !== 'archived');
      const requestedSite = availableSites.find((site) => site.id === nextSiteId)?.id || '';
      const persistedSite = bootstrap.persisted_active_site_id || availableSites.find((site) => site.is_active)?.id || '';
      const selectedSite = bootstrap.active_site_id || requestedSite || persistedSite || availableSites[0]?.id || '';
      setActiveSiteId(selectedSite);
      if (!selectedSite) {
        setPages([]);
        setActivePageId('');
        setActiveRouteId('');
        setActiveAssetId('');
        setActiveTarget({});
        setPreviewHtml('');
        setPreviewState(null);
        setSiteStatus(null);
        setChangeHistory(null);
        setShowNewWebsite(true);
        setInfoPanelOpen(false);
        return;
      }

      setShowNewWebsite(false);
      if (selectedSite !== persistedSite) {
        callBackend({ action: 'site_set_active', site_id: selectedSite }).catch((error: Error) => {
          if (runId === refreshRunRef.current) setNotice({ tone: 'warn', text: error.message });
        });
      }

      const map = bootstrap.sitemap || { site_id: selectedSite, items: [], routes: [], assets: [] };
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
      setActiveTarget(nextTarget || {});
      const previewRoute = selectedPage?.route || selectedRoute?.route || '/';
      postSelection(selectedSite, selectedPage, selectedRoute, selectedAsset, nextTarget);
      await renderSite(selectedSite, previewRoute, bootstrap.latest_preview || null);
      if (runId === refreshRunRef.current) {
        loadSiteDetails(selectedSite, runId);
      }
    } finally {
      if (runId === refreshRunRef.current) setPreviewLoading(false);
    }
  }

  async function loadSiteDetails(siteId: string, runId: number) {
    try {
      const [statusPayload, changesPayload] = await Promise.all([
        callBackend<SiteStatusPayload>({ action: 'site_status', site_id: siteId }),
        callBackend<ChangeHistoryPayload>({ action: 'list_changes', site_id: siteId })
      ]);
      if (runId !== refreshRunRef.current || activeSiteIdRef.current !== siteId) return;
      setSiteStatus(statusPayload);
      setChangeHistory(changesPayload);
    } catch (error) {
      if (runId === refreshRunRef.current) setNotice({ tone: 'warn', text: error instanceof Error ? error.message : 'Site details failed to load' });
    }
  }

  async function renderSite(siteId: string, route = '/', latestPreview?: RuntimeSummary['latest_preview'] | null) {
    if (latestPreview?.id && latestPreview.route === route && latestPreview.preview_url) {
      const payload = previewPayloadFromRecord(siteId, route, latestPreview);
      setPreviewState(payload);
      setPreviewHtml('');
      return;
    }
    const payload = await callBackend<PreviewPayload>({ action: 'build_preview', site_id: siteId, route, include_html: false });
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
        setActiveSiteId('');
        setPages([]);
        setActivePageId('');
        setActiveRouteId('');
        setActiveAssetId('');
        setActiveTarget({});
        setPreviewHtml('');
        setPreviewState(null);
        setSiteStatus(null);
        setChangeHistory(null);
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
      const componentFromRoute = appPage.startsWith('components/') ? appPage.slice('components/'.length) : '';
      const sectionFromRoute = appPage.startsWith('sections/') ? appPage.slice('sections/'.length) : '';
      const anchorFromRoute = appPage.startsWith('anchors/') ? appPage.slice('anchors/'.length) : '';
      const target: ActiveTarget = {
        id: componentFromRoute || sectionFromRoute || anchorFromRoute || '',
        componentId: payload.params?.component_id || componentFromRoute || '',
        kind: componentFromRoute ? 'component' : sectionFromRoute ? 'section' : anchorFromRoute ? 'anchor' : '',
        selector: payload.params?.target_selector || payload.params?.selector || '',
        anchor: payload.params?.target_anchor || payload.params?.anchor || ''
      };
      if (wantsInfoPanel) {
        setShowNewWebsite(false);
        setInfoPanelOpen(true);
        refresh(
          payload.params?.site_id || activeSiteIdRef.current,
          payload.params?.page_id || pageFromRoute || activePageIdRef.current,
          payload.params?.route || '',
          payload.params?.route_id || routeFromRoute,
          payload.params?.asset_id || assetFromRoute,
          target
        ).catch((error: Error) => setNotice({ tone: 'error', text: error.message }));
        return;
      }
      if (payload.params?.site_id || pageFromRoute || routeFromRoute || assetFromRoute || componentFromRoute || sectionFromRoute || anchorFromRoute || payload.params?.route) {
        setShowNewWebsite(false);
        setInfoPanelOpen(false);
        refresh(
          payload.params?.site_id || activeSiteIdRef.current,
          payload.params?.page_id || pageFromRoute,
          payload.params?.route || '',
          payload.params?.route_id || routeFromRoute,
          payload.params?.asset_id || assetFromRoute,
          target
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
          <h1>Ask an agent to connect a website.</h1>
          <p>
            The agent can walk you through a Drive ZIP import or a GitHub repository connection using a secret saved in
            Vault.
          </p>
          <div className="connection-guide-options" aria-label="Connection options">
            <span>Drive ZIP</span>
            <span>GitHub with Vault</span>
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
                  data-component-id={activeTarget.componentId || activeTarget.id || ''}
                  data-target-anchor={activeTarget.anchor || ''}
                  data-target-selector={activeTarget.selector || ''}
                  sandbox="allow-scripts allow-same-origin"
                  src={previewUrl}
                />
              ) : (
                <iframe
                  title={activePage?.title || activeSite?.display_name || 'Website preview'}
                  data-route-id={activeRouteId}
                  data-asset-id={activeAssetId}
                  data-component-id={activeTarget.componentId || activeTarget.id || ''}
                  data-target-anchor={activeTarget.anchor || ''}
                  data-target-selector={activeTarget.selector || ''}
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

function previewPayloadFromRecord(siteId: string, route: string, preview: NonNullable<RuntimeSummary['latest_preview']>): PreviewPayload {
  return {
    preview_id: String(preview.id || ''),
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
    html: ''
  };
}

function normalizePreviewUrl(rawUrl: string, target: ActiveTarget = {}): string {
  const value = rawUrl.trim();
  if (!value) return '';
  try {
    const url = new URL(value, window.location.origin);
    if (url.pathname === '/apps/website-studio/preview-runtime/' || url.pathname === '/apps/website-studio/preview-runtime') {
      url.searchParams.set('runtime_version', PREVIEW_RUNTIME_VERSION);
      url.searchParams.set('client_version', PREVIEW_CLIENT_VERSION);
    }
    if (target.selector) url.searchParams.set('target_selector', target.selector);
    else url.searchParams.delete('target_selector');
    if (target.anchor) url.searchParams.set('target_anchor', target.anchor);
    else url.searchParams.delete('target_anchor');
    if (target.id) url.searchParams.set('target_id', target.id);
    else url.searchParams.delete('target_id');
    if (target.kind) url.searchParams.set('target_kind', target.kind);
    else url.searchParams.delete('target_kind');
    if (url.origin === window.location.origin) {
      return `${url.pathname}${url.search}${url.hash}`;
    }
    return url.toString();
  } catch {
    return value;
  }
}

function postSelection(siteId: string, page?: Page, route?: Route, asset?: Asset, target: ActiveTarget = {}) {
  if (!siteId) return;
  const appPage = target.id && target.kind ? `${target.kind}s/${target.id}` : asset ? `assets/${asset.id}` : route ? `routes/${route.id}` : page ? `pages/${page.id}` : `sites/${siteId}`;
  const activeView = target.kind || (asset ? 'asset' : route && !page ? 'route' : page ? 'page' : 'site');
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
        component_id: target.componentId || '',
        target_selector: target.selector || '',
        target_anchor: target.anchor || '',
        route: page?.route || route?.route || '',
        title: target.selector || target.anchor || page?.title || route?.route || asset?.path || '',
        context_tool: 'website_page_context',
        app_page: appPage
      }
    },
    window.location.origin
  );
}
