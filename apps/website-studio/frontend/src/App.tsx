import { useEffect, useMemo, useRef, useState } from 'react';
import { isExactMaverickParentMessage } from '@maverick/pwa-cache';
import {
  callBackend,
  cachedWorkspaceSnapshot,
  invalidateWorkspaceSnapshots,
  type Asset,
  type BootstrapPayload,
  type ChangeHistoryPayload,
  type ChangeRecord,
  type Page,
  type PreviewPayload,
  type Route,
  type RuntimeSummary,
  type SitemapPayload,
  type Site,
  type SiteStatusPayload,
  type WorkspaceSnapshot
} from './api';

type Notice = { tone: 'ok' | 'warn' | 'error'; text: string } | null;
type ActiveTarget = { anchor?: string; componentId?: string; id?: string; kind?: string; selector?: string };
type RefreshOptions = { resetPreview?: boolean };
type RenderOptions = RefreshOptions & { runId?: number };
type Selection = { asset?: Asset; page?: Page; previewRoute: string; route?: Route };
type PreviewNavigateCommand = {
  owner_app_id: 'website-studio';
  preview_id: string;
  preview_url: string;
  route: string;
  target: ActiveTarget;
  type: 'website-studio.preview.navigate';
};

const EMPTY_SITEMAP: SitemapPayload = { site_id: '', items: [], routes: [], assets: [] };
const PREVIEW_RUNTIME_VERSION = 'preview-browser-stream-v6';
const PREVIEW_CLIENT_VERSION = 'website-studio-preview-frame-v9';

export function App() {
  const [sites, setSites] = useState<Site[]>([]);
  const [activeSiteId, setActiveSiteId] = useState('');
  const [sitemap, setSitemap] = useState<SitemapPayload>(EMPTY_SITEMAP);
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
  const [navigationLoadingLabel, setNavigationLoadingLabel] = useState('');
  const activeSiteIdRef = useRef('');
  const activePageIdRef = useRef('');
  const infoPanelOpenRef = useRef(false);
  const previewStateRef = useRef<PreviewPayload | null>(null);
  const previewCacheRef = useRef<Map<string, PreviewPayload>>(new Map());
  const previewRequestCacheRef = useRef<Map<string, Promise<PreviewPayload>>>(new Map());
  const previewSnapshotRevisionRef = useRef('');
  const refreshRunRef = useRef(0);
  const snapshotAbortRef = useRef<AbortController | null>(null);
  const sitemapRef = useRef<SitemapPayload>(EMPTY_SITEMAP);

  const pages = useMemo(() => sitemap.items || [], [sitemap]);
  const activeSite = useMemo(() => sites.find((site) => site.id === activeSiteId), [sites, activeSiteId]);
  const activePage = useMemo(() => pages.find((page) => page.id === activePageId), [pages, activePageId]);
  const activeRoute = useMemo(() => (sitemap.routes || []).find((route) => route.id === activeRouteId), [sitemap.routes, activeRouteId]);
  const loadingLabel = activePage?.title || routeDisplayName(activeRoute?.route || previewState?.route || '') || activeSite?.display_name || 'sito';
  const importOnly = showNewWebsite || !activeSite;
  const previewUrl = useMemo(() => normalizePreviewUrl(previewState?.preview_url || '', activeTarget), [activeTarget, previewState?.preview_url]);

  useEffect(() => {
    activeSiteIdRef.current = activeSiteId;
  }, [activeSiteId]);

  useEffect(() => {
    activePageIdRef.current = activePageId;
  }, [activePageId]);

  useEffect(() => {
    infoPanelOpenRef.current = infoPanelOpen;
  }, [infoPanelOpen]);

  useEffect(() => {
    sitemapRef.current = sitemap;
  }, [sitemap]);

  useEffect(() => {
    previewStateRef.current = previewState;
  }, [previewState]);

  async function refresh(
    nextSiteId = activeSiteIdRef.current,
    nextPageId = activePageIdRef.current,
    nextRoute = '',
    nextRouteId = '',
    nextAssetId = '',
    nextTarget: ActiveTarget = {},
    options: RefreshOptions = {}
  ) {
    const runId = ++refreshRunRef.current;
    const resetPreview = options.resetPreview ?? !previewStateRef.current;
    if (resetPreview) {
      setPreviewLoading(true);
      setPreviewHtml('');
      setPreviewState(null);
      previewStateRef.current = null;
    } else {
      setPreviewLoading(false);
    }
    const currentSiteId = activeSiteIdRef.current;
    if (resetPreview || (nextSiteId && nextSiteId !== currentSiteId)) {
      setSiteStatus(null);
      setChangeHistory(null);
    }
    try {
      snapshotAbortRef.current?.abort();
      const snapshotAbort = new AbortController();
      snapshotAbortRef.current = snapshotAbort;
      const snapshotRequest = cachedWorkspaceSnapshot(nextSiteId, nextRoute || '/', { revalidate: true, signal: snapshotAbort.signal });
      const initialSnapshot = await snapshotRequest.fresh;
      const bootstrap = snapshotToBootstrap(initialSnapshot);
      void snapshotRequest.revalidated.then((freshSnapshot) => {
        if (runId !== refreshRunRef.current || !freshSnapshot || freshSnapshot === initialSnapshot) return;
        return refresh(nextSiteId, nextPageId, nextRoute, nextRouteId, nextAssetId, nextTarget, { resetPreview: false });
      }).catch((error: Error) => {
        if (error.name !== 'AbortError' && runId === refreshRunRef.current) setNotice({ tone: 'warn', text: error.message });
      });
      if (runId !== refreshRunRef.current) return;
      // Aliases only trigger a reread; missed events cannot describe which
      // derived previews changed. Bind all routes and pending builds to the
      // accepted site's snapshot revision, including background revalidation.
      const previewRevision = JSON.stringify([initialSnapshot.project?.site.id, initialSnapshot.revision]);
      if (previewSnapshotRevisionRef.current !== previewRevision) {
        previewCacheRef.current.clear();
        previewRequestCacheRef.current.clear();
        previewSnapshotRevisionRef.current = previewRevision;
      }
      setSites(bootstrap.sites);
      const availableSites = bootstrap.sites.filter((site) => site.status !== 'archived');
      const requestedSite = availableSites.find((site) => site.id === nextSiteId)?.id || '';
      const persistedSite = bootstrap.persisted_active_site_id || availableSites.find((site) => site.is_active)?.id || '';
      const selectedSite = bootstrap.active_site_id || requestedSite || persistedSite || availableSites[0]?.id || '';
      setActiveSiteId(selectedSite);
      if (!selectedSite) {
        setSitemap(EMPTY_SITEMAP);
        setActivePageId('');
        setActiveRouteId('');
        setActiveAssetId('');
        setActiveTarget({});
        setPreviewHtml('');
        setPreviewState(null);
        previewStateRef.current = null;
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
      setSitemap(map);
      const selection = resolveSelection(map, nextPageId, nextRoute, nextRouteId, nextAssetId);
      setActivePageId(selection.page?.id || '');
      setActiveRouteId(selection.route?.id || '');
      setActiveAssetId(selection.asset?.id || '');
      setActiveTarget(nextTarget || {});
      postSelection(selectedSite, selection.page, selection.route, selection.asset, nextTarget);
      await renderSite(selectedSite, selection.previewRoute, bootstrap.latest_preview || null, { resetPreview, runId });
      if (runId === refreshRunRef.current && infoPanelOpenRef.current) {
        loadSiteDetails(selectedSite, runId);
      }
    } catch (error) {
      // Supersession and teardown are not failures of the current display.
      if (runId === refreshRunRef.current && !snapshotAbortRef.current?.signal.aborted) throw error;
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

  async function renderSite(siteId: string, route = '/', latestPreview?: RuntimeSummary['latest_preview'] | null, options: RenderOptions = {}) {
    const cacheKey = previewCacheKey(siteId, route);
    if (latestPreview?.id && latestPreview.route === route && latestPreview.preview_url) {
      const payload = previewPayloadFromRecord(siteId, route, latestPreview);
      applyPreviewPayload(payload, options.runId);
      return;
    }
    if (!options.resetPreview) {
      const cached = previewCacheRef.current.get(cacheKey);
      if (cached) {
        applyPreviewPayload(cached, options.runId);
        return;
      }
    }
    const pending =
      previewRequestCacheRef.current.get(cacheKey) ||
      callBackend<PreviewPayload>({ action: 'build_preview', site_id: siteId, route, include_html: false }).finally(() => {
        if (previewRequestCacheRef.current.get(cacheKey) === pending) previewRequestCacheRef.current.delete(cacheKey);
      });
    previewRequestCacheRef.current.set(cacheKey, pending);
    const payload = await pending;
    applyPreviewPayload(payload, options.runId);
  }

  function applyPreviewPayload(payload: PreviewPayload, runId?: number) {
    if (runId && runId !== refreshRunRef.current) return;
    previewCacheRef.current.set(previewCacheKey(payload.site_id, payload.route || '/'), payload);
    while (previewCacheRef.current.size > 12) {
      const oldest = previewCacheRef.current.keys().next().value;
      if (oldest) previewCacheRef.current.delete(oldest);
      else break;
    }
    previewStateRef.current = payload;
    setPreviewState(payload);
    setPreviewHtml(payload.html || '');
  }

  async function navigateLoadedSite(
    nextSiteId: string,
    nextPageId: string,
    nextRoute: string,
    nextRouteId: string,
    nextAssetId: string,
    nextTarget: ActiveTarget,
    wantsInfoPanel: boolean
  ): Promise<boolean> {
    const siteId = nextSiteId || activeSiteIdRef.current;
    const map = sitemapRef.current;
    if (!siteId || siteId !== activeSiteIdRef.current || map.site_id !== siteId) return false;
    if (!(map.items?.length || map.routes?.length || map.assets?.length)) return false;

    const selection = resolveSelection(map, nextPageId, nextRoute, nextRouteId, nextAssetId);
    if ((nextPageId || nextRoute || nextRouteId || nextAssetId) && !selection.page && !selection.route && !selection.asset) {
      return false;
    }

    const runId = ++refreshRunRef.current;
    setShowNewWebsite(false);
    setInfoPanelOpen(wantsInfoPanel);
    setPreviewLoading(false);
    setActivePageId(selection.page?.id || '');
    setActiveRouteId(selection.route?.id || '');
    setActiveAssetId(selection.asset?.id || '');
    setActiveTarget(nextTarget || {});
    postSelection(siteId, selection.page, selection.route, selection.asset, nextTarget);
    await renderSite(siteId, selection.previewRoute, null, { resetPreview: false, runId });
    if (runId === refreshRunRef.current && wantsInfoPanel) {
      loadSiteDetails(siteId, runId);
    }
    return true;
  }

  useEffect(() => {
    refresh().catch((error: Error) => setNotice({ tone: 'error', text: error.message }));
    return () => snapshotAbortRef.current?.abort();
  }, []);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (!isExactMaverickParentMessage(event) || !event.data || typeof event.data !== 'object') return;
      const payload = event.data as { type?: string; resource?: string; params?: Record<string, string> };
      if (payload.type === 'maverick.app.data-changed' && (payload as { owner_app_id?: string }).owner_app_id === 'website-studio') {
        const resource = payload.resource || '';
        const resetsPreview = ['source', 'navigation'].includes(resource);
        if (resetsPreview) {
          previewCacheRef.current.clear();
          previewRequestCacheRef.current.clear();
        }
        invalidateWorkspaceSnapshots(resource ? [resource] : []);
        refresh(activeSiteIdRef.current, activePageIdRef.current, '', '', '', {}, { resetPreview: resetsPreview }).catch((error: Error) =>
          setNotice({ tone: 'error', text: error.message })
        );
        return;
      }
      if (payload.type !== 'maverick.app.navigate') return;
      if (payload.params?.new_website_request_id) {
        setActiveSiteId('');
        setSitemap(EMPTY_SITEMAP);
        setActivePageId('');
        setActiveRouteId('');
        setActiveAssetId('');
        setActiveTarget({});
        setPreviewHtml('');
        setPreviewState(null);
        previewStateRef.current = null;
        previewCacheRef.current.clear();
        previewRequestCacheRef.current.clear();
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
        const siteId = payload.params?.site_id || activeSiteIdRef.current;
        const pageId = payload.params?.page_id || pageFromRoute || activePageIdRef.current;
        const route = payload.params?.route || '';
        const routeId = payload.params?.route_id || routeFromRoute;
        const assetId = payload.params?.asset_id || assetFromRoute;
        navigateLoadedSite(siteId, pageId, route, routeId, assetId, target, true)
          .then((handled) => {
            if (handled) return;
            return refresh(siteId, pageId, route, routeId, assetId, target, { resetPreview: !previewStateRef.current });
          })
          .catch((error: Error) => setNotice({ tone: 'error', text: error.message }));
        return;
      }
      if (payload.params?.site_id || pageFromRoute || routeFromRoute || assetFromRoute || componentFromRoute || sectionFromRoute || anchorFromRoute || payload.params?.route) {
        setShowNewWebsite(false);
        setInfoPanelOpen(false);
        const siteId = payload.params?.site_id || activeSiteIdRef.current;
        const pageId = payload.params?.page_id || pageFromRoute;
        const route = payload.params?.route || '';
        const routeId = payload.params?.route_id || routeFromRoute;
        const assetId = payload.params?.asset_id || assetFromRoute;
        if (pageId || route || routeId) {
          setNavigationLoadingLabel(navigationLoadingName(sitemapRef.current, pageId, routeId, route));
        }
        navigateLoadedSite(siteId, pageId, route, routeId, assetId, target, false)
          .then((handled) => {
            if (handled) return;
            return refresh(siteId, pageId, route, routeId, assetId, target, { resetPreview: !previewStateRef.current });
          })
          .catch((error: Error) => {
            setNavigationLoadingLabel('');
            setNotice({ tone: 'error', text: error.message });
          });
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
          {previewLoading && !(previewUrl || previewHtml) ? (
            <PreviewLoadingState label={loadingLabel} />
          ) : previewUrl || previewHtml ? (
            <>
              {previewUrl && previewState ? (
                <WarmPreviewFrame
                  title={activePage?.title || activeSite?.display_name || 'Website preview'}
                  preview={previewState}
                  previewUrl={previewUrl}
                  activeRouteId={activeRouteId}
                  activeAssetId={activeAssetId}
                  activeTarget={activeTarget}
                  loadingLabel={loadingLabel}
                  onDocumentReady={() => setNavigationLoadingLabel('')}
                />
              ) : (
                <InlinePreviewFrame
                  title={activePage?.title || activeSite?.display_name || 'Website preview'}
                  activeRouteId={activeRouteId}
                  activeAssetId={activeAssetId}
                  activeTarget={activeTarget}
                  html={previewHtml}
                  loadingLabel={loadingLabel}
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
              {navigationLoadingLabel ? <PreviewLoadingState label={navigationLoadingLabel} overlay /> : null}
            </>
          ) : (
            <div className="site-empty">No renderable page in this site.</div>
          )}
        </section>
      )}
    </main>
  );
}

/*
 * Everything below this point is pure helper/rendering code. The warm preview
 * frame deliberately owns iframe navigation so React state changes do not
 * remount the browser context that already loaded the site's assets.
 */

function WarmPreviewFrame({
  activeAssetId,
  activeRouteId,
  activeTarget,
  preview,
  previewUrl,
  loadingLabel,
  onDocumentReady,
  title
}: {
  activeAssetId: string;
  activeRouteId: string;
  activeTarget: ActiveTarget;
  preview: PreviewPayload;
  previewUrl: string;
  loadingLabel: string;
  onDocumentReady: () => void;
  title: string;
}) {
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const lastPreviewRef = useRef<PreviewPayload | null>(null);
  const pendingCommandRef = useRef<PreviewNavigateCommand | null>(null);
  const [mountedUrl, setMountedUrl] = useState(previewUrl);
  const [readyPreviewId, setReadyPreviewId] = useState('');

  useEffect(() => {
    function handleDocumentReady(event: MessageEvent) {
      if (event.origin !== window.location.origin || event.source !== frameRef.current?.contentWindow) return;
      const payload = event.data as { owner_app_id?: string; preview_id?: string; type?: string } | null;
      if (payload?.type !== 'website-studio.preview.document-ready' || payload.owner_app_id !== 'website-studio') return;
      if (payload.preview_id !== preview.preview_id) return;
      setReadyPreviewId(payload.preview_id);
      onDocumentReady();
    }
    window.addEventListener('message', handleDocumentReady);
    return () => window.removeEventListener('message', handleDocumentReady);
  }, [onDocumentReady, preview.preview_id]);

  useEffect(() => {
    if (!previewUrl) return;
    const previous = lastPreviewRef.current;
    const command = previewNavigateCommand(preview, previewUrl, activeTarget);
    const warm = Boolean(mountedUrl && previous && canWarmNavigatePreview(previous, preview));
    lastPreviewRef.current = preview;
    pendingCommandRef.current = command;
    if (!warm) {
      setMountedUrl(previewUrl);
      return;
    }
    postPreviewNavigate(frameRef.current, command);
  }, [activeTarget.anchor, activeTarget.componentId, activeTarget.id, activeTarget.kind, activeTarget.selector, mountedUrl, preview, previewUrl]);

  function handleLoad() {
    const command = pendingCommandRef.current;
    if (command) postPreviewNavigate(frameRef.current, command);
  }

  return (
    <>
      <iframe
      ref={frameRef}
      title={title}
      data-route-id={activeRouteId}
      data-asset-id={activeAssetId}
      data-component-id={activeTarget.componentId || activeTarget.id || ''}
      data-target-anchor={activeTarget.anchor || ''}
      data-target-selector={activeTarget.selector || ''}
      data-preview-url={previewUrl}
      sandbox="allow-scripts allow-same-origin"
      src={mountedUrl}
      onLoad={handleLoad}
      />
      {readyPreviewId !== preview.preview_id ? <PreviewLoadingState label={loadingLabel} overlay /> : null}
    </>
  );
}

function PreviewLoadingState({ label, overlay = false }: { label: string; overlay?: boolean }) {
  const text = `Caricamento ${label}`;
  return (
    <div className={`preview-loading-state${overlay ? ' is-overlay' : ''}`} role="status" aria-label={text}>
      <span className="preview-loading-indicator" aria-hidden="true">
        <span className="preview-loading-shape" />
      </span>
      <span className="preview-loading-label">{text}</span>
    </div>
  );
}

function InlinePreviewFrame({ activeAssetId, activeRouteId, activeTarget, html, loadingLabel, title }: {
  activeAssetId: string;
  activeRouteId: string;
  activeTarget: ActiveTarget;
  html: string;
  loadingLabel: string;
  title: string;
}) {
  const [readyHtml, setReadyHtml] = useState('');
  return (
    <>
      <iframe
        title={title}
        data-route-id={activeRouteId}
        data-asset-id={activeAssetId}
        data-component-id={activeTarget.componentId || activeTarget.id || ''}
        data-target-anchor={activeTarget.anchor || ''}
        data-target-selector={activeTarget.selector || ''}
        sandbox=""
        srcDoc={html}
        onLoad={() => setReadyHtml(html)}
      />
      {readyHtml !== html ? <PreviewLoadingState label={loadingLabel} overlay /> : null}
    </>
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

function resolveSelection(map: SitemapPayload, nextPageId = '', nextRoute = '', nextRouteId = '', nextAssetId = ''): Selection {
  const routes = map.routes || [];
  const assets = map.assets || [];
  const pages = map.items || [];
  const route = routes.find((item) => item.id === nextRouteId) || routes.find((item) => item.route === nextRoute);
  const asset = assets.find((item) => item.id === nextAssetId);
  const page =
    pages.find((item) => item.id === nextPageId) ||
    (route?.page_id ? pages.find((item) => item.id === route.page_id) : undefined) ||
    pages.find((item) => item.route === nextRoute) ||
    (route && !route.page_id ? undefined : pages[0]);
  return {
    asset,
    page,
    previewRoute: page?.route || route?.route || nextRoute || '/',
    route
  };
}

function routeDisplayName(route = ''): string {
  const segment = route.split(/[?#]/, 1)[0].split('/').filter(Boolean).pop() || '';
  if (!segment) return 'Home';
  return segment.replace(/[-_]+/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function navigationLoadingName(map: SitemapPayload, pageId = '', routeId = '', route = ''): string {
  const selectedRoute = (map.routes || []).find((item) => item.id === routeId || item.route === route);
  const selectedPage = (map.items || []).find((item) => item.id === pageId || item.id === selectedRoute?.page_id || item.route === route || item.route === selectedRoute?.route);
  return selectedPage?.title || routeDisplayName(selectedRoute?.route || route) || 'pagina';
}

function snapshotToBootstrap(snapshot: WorkspaceSnapshot): BootstrapPayload {
  const workspace = snapshot.workspace || { projects: [], active_project_id: '', persisted_active_project_id: '' };
  const project = snapshot.project || null;
  return {
    sites: workspace.projects,
    active_site_id: workspace.active_project_id,
    persisted_active_site_id: workspace.persisted_active_project_id,
    sitemap: project ? {
      site_id: project.navigation.site_id,
      items: project.navigation.pages || [],
      routes: project.navigation.routes || [],
      assets: []
    } : EMPTY_SITEMAP,
    latest_preview: project?.latest_preview || null
  };
}

function previewCacheKey(siteId: string, route = '/') {
  return `${siteId}::${route || '/'}`;
}

function previewNavigateCommand(preview: PreviewPayload, previewUrl: string, target: ActiveTarget): PreviewNavigateCommand {
  return {
    type: 'website-studio.preview.navigate',
    owner_app_id: 'website-studio',
    preview_id: preview.preview_id,
    preview_url: previewUrl,
    route: preview.route || '/',
    target
  };
}

function canWarmNavigatePreview(previous: PreviewPayload, next: PreviewPayload): boolean {
  return (
    previous.site_id === next.site_id &&
    previous.environment_id === next.environment_id &&
    previous.runtime_kind === next.runtime_kind &&
    (previous.build_id || '') === (next.build_id || '') &&
    isRuntimePreviewUrl(previous.preview_url) &&
    isRuntimePreviewUrl(next.preview_url)
  );
}

function isRuntimePreviewUrl(value: string): boolean {
  try {
    const url = new URL(value, window.location.origin);
    return url.origin === window.location.origin && (url.pathname === '/apps/website-studio/preview-runtime/' || url.pathname === '/apps/website-studio/preview-runtime');
  } catch {
    return false;
  }
}

function postPreviewNavigate(frame: HTMLIFrameElement | null, command: PreviewNavigateCommand) {
  frame?.contentWindow?.postMessage(command, window.location.origin);
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
    "*"
  );
}
