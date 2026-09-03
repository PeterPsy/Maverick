import { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { isExactMaverickParentMessage } from '@maverick/pwa-cache';
import { cachedWorkspaceSnapshot, invalidateWorkspaceSnapshots, type WorkspaceSnapshot } from '../../api';
import {
  TreeExpander,
  TreeIcon,
  TreeLabel,
  TreeNode,
  TreeNodeContent,
  TreeNodeTrigger,
  TreeProvider,
  TreeView,
} from '../../components/ui/tree';
import './styles.css';

type TreeItem = {
  anchor?: string;
  changed?: boolean;
  children?: TreeItem[];
  empty?: boolean;
  entityId?: string;
  id: string;
  kind: string;
  label: string;
  pageId?: string;
  route?: string;
  routeId?: string;
  selector?: string;
  status?: string;
  subtitle?: string;
  warning?: boolean;
};

type Site = {
  display_name?: string;
  id?: string;
  is_active?: boolean;
  status?: string;
};

type VisualComponent = {
  anchor?: string;
  changed?: boolean;
  confidence?: string;
  id?: string;
  kind?: string;
  label?: string;
  page_id?: string;
  route?: string;
  selector?: string;
  source_files?: string[];
  status?: string;
  warnings?: unknown[];
};

type VisualPage = {
  aliases?: string[];
  anchors?: VisualComponent[];
  canonical_route?: string;
  changed?: boolean;
  components?: VisualComponent[];
  id?: string;
  kind?: string;
  label?: string;
  route?: string;
  route_id?: string;
  sections?: VisualComponent[];
  source_files?: string[];
  status?: string;
  title?: string;
  warnings?: unknown[];
};

type VisualNavigationPayload = {
  inventory_summary?: { asset_count?: number; page_count?: number; route_count?: number; source_inventory_hidden?: boolean };
  pages?: VisualPage[];
  routes?: VisualPage[];
  site?: { display_name?: string; id?: string; slug?: string; source_provider?: string; status?: string };
  site_id?: string;
  status?: {
    changed_files_count?: number;
    latest_build_id?: string;
    latest_build_status?: string;
    latest_preview_id?: string;
    missing_requirements?: string[];
    runtime_kind?: string;
    runtime_status?: string;
  };
  warnings?: Array<{ message?: string; route?: string; scope?: string }>;
};

type ChangesPayload = {
  builds?: Array<Record<string, unknown>>;
  publish_requests?: Array<Record<string, unknown>>;
  working_diff?: Array<{ path?: string }>;
};

const DEFAULT_EXPANDED_IDS = ['site:root', 'group:pages'];

async function backend<T>(body: Record<string, unknown>, signal?: AbortSignal): Promise<T> {
  const response = await fetch('/api/apps/website-studio/backend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal
  });
  if (!response.ok) throw new Error('backend request failed');
  return response.json() as Promise<T>;
}

function WebsiteSitemapSidebarWidget() {
  const [sites, setSites] = useState<Site[]>([]);
  const [navigation, setNavigation] = useState<VisualNavigationPayload | null>(null);
  const [changeHistory, setChangeHistory] = useState<ChangesPayload | null>(null);
  const [activeSiteId, setActiveSiteId] = useState('');
  const [selectedNodeId, setSelectedNodeId] = useState('');
  const [query, setQuery] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  const loadAbortRef = useRef<AbortController | null>(null);

  const filteredSites = useMemo(() => sites.filter((site) => site.status !== 'archived'), [sites]);
  const treeItems = useMemo(
    () => activeSiteId && navigation ? filterTree(buildTree(navigation, changeHistory), query.trim().toLowerCase()) : [],
    [activeSiteId, changeHistory, navigation, query]
  );
  const defaultExpandedIds = useMemo(() => collectDefaultExpandedIds(treeItems, Boolean(query.trim())), [query, treeItems]);
  const treeProviderKey = activeSiteId || 'site';

  async function load(nextSiteId = activeSiteId) {
    if (!navigation) setIsLoading(true);
    loadAbortRef.current?.abort();
    const controller = new AbortController();
    loadAbortRef.current = controller;
    const request = cachedWorkspaceSnapshot(nextSiteId, '/', { revalidate: true, signal: controller.signal });
    const snapshot = await request.fresh;
    const selectedSiteId = applySnapshot(snapshot, nextSiteId);
    void request.revalidated.then(async (fresh) => {
      if (!fresh || controller.signal.aborted) return;
      const freshSiteId = applySnapshot(fresh, nextSiteId);
      if (freshSiteId) await hydrateVisualNavigation(freshSiteId, controller.signal);
    }).catch((loadError: Error) => {
      if (loadError.name !== 'AbortError' && !controller.signal.aborted) setError(loadError.message);
    });
    if (selectedSiteId) await hydrateVisualNavigation(selectedSiteId, controller.signal);
  }

  function applySnapshot(snapshot: WorkspaceSnapshot, requestedSiteId = ''): string {
    const nextSites = snapshot.workspace?.projects || [];
    setSites(nextSites);
    const selectableSites = nextSites.filter((item) => item.status !== 'archived');
    const requestedSite = selectableSites.find((item) => item.id === requestedSiteId);
    const persistedSite = selectableSites.find((item) => item.is_active);
    const site = requestedSite || persistedSite || selectableSites.find((item) => item.id === snapshot.workspace?.active_project_id) || selectableSites[0];
    if (!site?.id) {
      setActiveSiteId('');
      setNavigation(null);
      setChangeHistory(null);
      setError('');
      setIsLoading(false);
      return '';
    }
    setActiveSiteId(site.id);
    const project = snapshot.project;
    const navigationPayload = project?.navigation as VisualNavigationPayload | undefined;
    const changedCount = project?.working_state.changed_files_count || 0;
    setNavigation(navigationPayload ? { ...navigationPayload, status: { ...navigationPayload.status, changed_files_count: changedCount } } : null);
    setChangeHistory({ working_diff: Array.from({ length: changedCount }, () => ({})) });
    setError('');
    setIsLoading(false);
    return site.id;
  }

  async function hydrateVisualNavigation(siteId: string, signal: AbortSignal) {
    const visual = await backend<VisualNavigationPayload>({ action: 'navigation_analyze', site_id: siteId }, signal);
    if (signal.aborted) return;
    setNavigation(visual || null);
  }

  useEffect(() => {
    load().catch((loadError: Error) => {
      if (loadError.name === 'AbortError') return;
      setError(loadError.message || 'Visual navigation unavailable.');
      setIsLoading(false);
    });
    return () => loadAbortRef.current?.abort();
  }, []);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (!isExactMaverickParentMessage(event) || !event.data || typeof event.data !== 'object') return;
      const payload = event.data as { context?: { content?: { payload?: { active_app_params?: Record<string, string> } } }; owner_app_id?: string; resource?: string; type?: string };
      if (payload.type === 'maverick.widget.data-changed' && payload.owner_app_id === 'website-studio') {
        invalidateWorkspaceSnapshots(payload.resource ? [payload.resource] : []);
        load(activeSiteId).catch((loadError: Error) => { if (loadError.name !== 'AbortError') setError(loadError.message || 'Visual navigation unavailable.'); });
        return;
      }
      if (payload.type !== 'maverick.widget.context-changed') return;
      const params = payload.context?.content?.payload?.active_app_params || {};
      if (params.site_id && params.site_id !== activeSiteId) {
        load(String(params.site_id)).catch((loadError: Error) => { if (loadError.name !== 'AbortError') setError(loadError.message || 'Visual navigation unavailable.'); });
      }
    }
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [activeSiteId]);

  async function selectSite(siteId: string) {
    setActiveSiteId(siteId);
    if (!siteId) {
      setNavigation(null);
      setChangeHistory(null);
      setSelectedNodeId('');
      setError('');
      return;
    }
    await backend({ action: 'site_set_active', site_id: siteId }).catch(() => null);
    window.parent?.postMessage({ type: 'maverick.widget.open-app', app_id: 'website-studio', params: { site_id: siteId } }, "*");
    await load(siteId);
  }

  function selectNode(node: TreeItem) {
    setSelectedNodeId(node.id);
    if (node.empty || !isActionable(node)) return;
    openNode(node, activeSiteId);
  }

  return (
    <main className="website-studio-sitemap-widget">
      <label className="website-studio-sitemap-search">
        <span className="website-studio-sitemap-search-icon" aria-hidden="true" />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search visual site" />
      </label>
      <label className="website-studio-sitemap-select-frame">
        <select aria-label="Select a site" value={activeSiteId} onChange={(event) => void selectSite(event.target.value)}>
          <option value="">Select a site</option>
          {filteredSites.length ? filteredSites.map((site) => (
            <option key={site.id || site.display_name} value={site.id || ''}>{site.display_name || site.id}</option>
          )) : <option value="" disabled>No active websites yet</option>}
        </select>
      </label>
      <div className="website-studio-sitemap-list storage-sidebar-tree-list">
        {isLoading ? <WebsiteTreeSkeleton /> : error ? <p className="website-studio-sitemap-empty">{error}</p> : !activeSiteId ? (
          <p className="website-studio-sitemap-empty">{filteredSites.length ? 'Select a site to load its visual navigation.' : 'No active websites yet.'}</p>
        ) : treeItems.length ? (
          <TreeProvider
            animateExpand
            className="storage-folder-tree website-studio-folder-tree"
            defaultExpandedIds={defaultExpandedIds}
            indent={18}
            key={treeProviderKey}
            onSelectionChange={(ids) => setSelectedNodeId(ids[ids.length - 1] || '')}
            selectedIds={selectedNodeId ? [selectedNodeId] : []}
          >
            <TreeView>
              {treeItems.map((node, index) => (
                <WebsiteTreeNodeView
                  isLast={index === treeItems.length - 1}
                  key={node.id}
                  level={0}
                  node={node}
                  onSelect={selectNode}
                />
              ))}
            </TreeView>
          </TreeProvider>
        ) : <p className="website-studio-sitemap-empty">No matching visual site items.</p>}
      </div>
    </main>
  );
}

function WebsiteTreeNodeView({ node, level, isLast, onSelect }: { isLast: boolean; level: number; node: TreeItem; onSelect: (node: TreeItem) => void }) {
  const hasChildren = Boolean(node.children?.length);
  const label = node.empty ? node.label : node.label || node.id;
  return (
    <TreeNode isLast={isLast} level={level} nodeId={node.id}>
      <TreeNodeTrigger
        className={`website-studio-tree-trigger${node.warning ? ' has-warning' : ''}${node.changed ? ' has-change' : ''}${node.empty ? ' is-empty' : ''}`}
        onClick={() => onSelect(node)}
        toggleOnTriggerClick={false}
      >
        <TreeExpander className="website-studio-tree-expander" hasChildren={hasChildren} />
        <TreeIcon hasChildren={hasChildren} />
        <TreeLabel title={node.subtitle || label}>{label}</TreeLabel>
        {node.status ? <span className={`website-studio-tree-badge${node.warning ? ' warn' : ''}${node.changed ? ' changed' : ''}`}>{node.status}</span> : null}
      </TreeNodeTrigger>
      <TreeNodeContent hasChildren={hasChildren}>
        {(node.children || []).map((child, index) => (
          <WebsiteTreeNodeView
            isLast={index === (node.children || []).length - 1}
            key={child.id}
            level={level + 1}
            node={child}
            onSelect={onSelect}
          />
        ))}
      </TreeNodeContent>
    </TreeNode>
  );
}

function buildTree(navigation: VisualNavigationPayload, changeHistory: ChangesPayload | null): TreeItem[] {
  const pages = navigation.pages || [];
  const routes = navigation.routes || [];
  const warnings = navigation.warnings || [];
  const pageNodes = pages
    .slice()
    .sort((left, right) => String(left.route || '').localeCompare(String(right.route || '')))
    .map(pageNode);
  if (!pageNodes.length) pageNodes.push(emptyNode('No visual pages', 'preview has no navigable pages'));

  const routeNodes = routes
    .slice()
    .sort((left, right) => String(left.route || '').localeCompare(String(right.route || '')))
    .map(routeNode);
  const children: TreeItem[] = [groupNode('group:pages', 'Pages', `${pages.length}`, pageNodes)];
  if (routeNodes.length) children.push(groupNode('group:routes', 'Other routes', `${routeNodes.length}`, routeNodes));
  if (warnings.length) children.push(groupNode('group:warnings', 'Warnings', `${warnings.length}`, warnings.map((warning, index) => warningNode(warning, index))));
  const site = navigation.site || {};
  const changedCount = Number(navigation.status?.changed_files_count || changeHistory?.working_diff?.length || 0);
  const runtimeStatus = String(navigation.status?.runtime_status || site.status || 'unknown').replace('_', ' ');
  return [
    {
      id: 'site:root',
      kind: 'site',
      entityId: String(site.id || navigation.site_id || ''),
      label: String(site.display_name || site.slug || navigation.site_id || 'Website'),
      subtitle: statusSummary(navigation, changeHistory),
      status: changedCount ? `${changedCount} modified` : runtimeStatus,
      changed: Boolean(changedCount),
      warning: Boolean(warnings.length),
      children
    }
  ];
}

function pageNode(page: VisualPage): TreeItem {
  const sections = uniqueVisualItems([...(page.sections || []), ...(page.anchors || [])]).map((item) => visualItemNode(item, page, item.kind === 'anchor' ? 'anchor' : 'section'));
  const components = (page.components || []).map((item) => visualItemNode(item, page, 'component'));
  const children: TreeItem[] = [];
  if (sections.length) children.push(groupNode(`sections:${page.id}`, 'Sections', `${sections.length}`, sections));
  if (components.length) children.push(groupNode(`components:${page.id}`, 'Components', `${components.length}`, components));
  return {
    id: `page:${page.id}`,
    kind: 'page',
    entityId: String(page.id || ''),
    pageId: String(page.id || ''),
    route: String(page.route || ''),
    routeId: String(page.route_id || ''),
    label: String(page.label || page.title || page.route || page.id),
    subtitle: page.aliases?.length ? `${String(page.route || 'page')} +${page.aliases.length} aliases` : String(page.route || 'page'),
    status: page.changed ? 'modified' : page.warnings?.length ? 'warning' : '',
    warning: Boolean(page.warnings?.length),
    changed: Boolean(page.changed),
    children
  };
}

function routeNode(route: VisualPage): TreeItem {
  const components = (route.components || []).map((item) => visualItemNode(item, route, 'component'));
  return {
    id: `route:${route.id}`,
    kind: 'route',
    entityId: String(route.id || ''),
    routeId: String(route.id || ''),
    route: String(route.route || ''),
    label: String(route.label || route.title || route.route || route.id),
    subtitle: String(route.status || 'rendered route'),
    status: route.changed ? 'modified' : route.warnings?.length ? 'warning' : String(route.status || ''),
    warning: Boolean(route.warnings?.length),
    changed: Boolean(route.changed),
    children: components.length ? [groupNode(`components:${route.id}`, 'Components', `${components.length}`, components)] : []
  };
}

function visualItemNode(item: VisualComponent, page: VisualPage, kind: 'anchor' | 'component' | 'section'): TreeItem {
  const confidence = item.confidence ? String(item.confidence).replace('_', ' ') : kind;
  return {
    id: `${kind}:${item.id}`,
    kind,
    entityId: String(item.id || ''),
    pageId: String(item.page_id || page.id || ''),
    routeId: String(page.route_id || ''),
    route: String(item.route || page.route || ''),
    selector: String(item.selector || ''),
    anchor: String(item.anchor || ''),
    label: String(item.label || item.selector || item.id),
    subtitle: String(item.selector || item.anchor || confidence),
    status: item.changed ? 'modified' : item.warnings?.length ? 'warning' : '',
    warning: Boolean(item.warnings?.length),
    changed: Boolean(item.changed || page.changed)
  };
}

function statusSummary(navigation: VisualNavigationPayload, changeHistory: ChangesPayload | null) {
  const latestBuild = (changeHistory?.builds || [])[0] || {};
  const latestRequest = (changeHistory?.publish_requests || [])[0] || {};
  const runtime = String(navigation.status?.runtime_status || 'unknown').replace('_', ' ');
  const build = String(navigation.status?.latest_build_status || latestBuild.status || 'none');
  const request = String(latestRequest.status || 'none');
  return `runtime ${runtime} | build ${build} | request ${request}`;
}

function warningNode(warning: { message?: string; route?: string; scope?: string }, index: number): TreeItem {
  return {
    id: `warning:${index}`,
    kind: 'warning',
    label: String(warning.message || 'Warning'),
    subtitle: [warning.scope, warning.route].filter(Boolean).join(' | '),
    status: 'warning',
    warning: true
  };
}

function groupNode(id: string, label: string, subtitle: string, children: TreeItem[]): TreeItem {
  return { id, kind: 'group', label, subtitle, status: String(children.filter((child) => !child.empty).length), children };
}

function emptyNode(label: string, subtitle: string): TreeItem {
  return { id: `empty:${label}`, kind: 'empty', label, subtitle, status: 'empty', empty: true };
}

function uniqueVisualItems(items: VisualComponent[]) {
  const seen = new Set<string>();
  const result: VisualComponent[] = [];
  for (const item of items) {
    const key = String(item.id || `${item.kind}:${item.selector}:${item.anchor}:${item.label}`);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    result.push(item);
  }
  return result;
}

function filterTree(nodes: TreeItem[], needle: string): TreeItem[] {
  if (!needle) return nodes;
  return nodes.map((node) => filterNode(node, needle)).filter((node): node is TreeItem => Boolean(node));
}

function filterNode(node: TreeItem, needle: string): TreeItem | null {
  const children = (node.children || []).map((child) => filterNode(child, needle)).filter((child): child is TreeItem => Boolean(child));
  if (nodeMatches(node, needle)) return { ...node, children: node.children || [] };
  if (children.length) return { ...node, children };
  return null;
}

function nodeMatches(node: TreeItem, needle: string) {
  return `${node.label || ''} ${node.subtitle || ''} ${node.status || ''} ${node.route || ''} ${node.selector || ''}`.toLowerCase().includes(needle);
}

function collectDefaultExpandedIds(nodes: TreeItem[], expandAll: boolean) {
  const ids: string[] = [];
  function visit(current: TreeItem) {
    const shouldExpand = expandAll || DEFAULT_EXPANDED_IDS.includes(current.id);
    if (current.children?.length && shouldExpand) ids.push(current.id);
    if (shouldExpand) current.children?.forEach(visit);
  }
  nodes.forEach(visit);
  return ids;
}

function isActionable(node: TreeItem) {
  return Boolean(node.entityId && ['site', 'page', 'route', 'section', 'anchor', 'component'].includes(node.kind));
}

function openNode(node: TreeItem, activeSiteId: string) {
  if (!isActionable(node)) return;
  const kind = node.kind;
  const id = String(node.entityId || '');
  const appPageKind = kind === 'anchor' ? 'anchors' : `${kind}s`;
  const params: Record<string, string> = { site_id: activeSiteId, app_page: `${appPageKind}/${id}` };
  if (kind === 'site') {
    params.app_page = `sites/${id}`;
  }
  if (kind === 'page') {
    params.page_id = node.pageId || id;
    params.route = node.route || '';
  }
  if (kind === 'route') {
    params.route_id = node.routeId || id;
    params.route = node.route || '';
  }
  if (kind === 'section' || kind === 'anchor' || kind === 'component') {
    params.page_id = node.pageId || '';
    params.route_id = node.routeId || '';
    params.route = node.route || '';
    params.target_selector = node.selector || '';
    params.target_anchor = node.anchor || '';
    if (kind === 'component') params.component_id = id;
    if (kind === 'section') params.section_id = id;
    if (kind === 'anchor') params.anchor_id = id;
  }
  window.parent?.postMessage({ type: 'maverick.widget.open-app', app_id: 'website-studio', params }, "*");
  window.parent?.postMessage({ type: 'maverick.shell.sidebar.close' }, "*");
}

function WebsiteTreeSkeleton() {
  return (
    <div className="website-studio-sitemap-skeleton" role="status" aria-label="Website visual navigation is loading">
      {Array.from({ length: 8 }).map((_, index) => (
        <div className={`website-studio-sitemap-skeleton__row depth-${Math.min(index, 3)}`} key={index} aria-hidden="true">
          <span className="website-studio-sitemap-skeleton__expander" />
          <span className="website-studio-sitemap-skeleton__icon" />
          <span className="website-studio-sitemap-skeleton__copy" />
        </div>
      ))}
    </div>
  );
}

createRoot(document.getElementById('website-studio-sitemap-sidebar-root') as HTMLElement).render(<WebsiteSitemapSidebarWidget />);
