import { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
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
  assetId?: string;
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
  status?: string;
  subtitle?: string;
  warning?: boolean;
};

type BackendPage = Record<string, unknown> & {
  id?: string;
  route?: string;
  source_files?: string[];
  title?: string;
  warnings?: unknown[];
};

type BackendRoute = Record<string, unknown> & {
  id?: string;
  kind?: string;
  page_id?: string;
  route?: string;
  source_files?: string[];
  status?: string;
  warnings?: unknown[];
};

type BackendAsset = Record<string, unknown> & {
  id?: string;
  kind?: string;
  path?: string;
  source_files?: string[];
  warnings?: unknown[];
};

type Site = {
  display_name?: string;
  id?: string;
  is_active?: boolean;
  status?: string;
};

type SitemapPayload = {
  assets?: BackendAsset[];
  items?: BackendPage[];
  routes?: BackendRoute[];
};

type ChangesPayload = {
  builds?: Array<Record<string, unknown>>;
  publish_requests?: Array<Record<string, unknown>>;
  working_diff?: Array<{ path?: string }>;
};

type AssetBuckets = {
  assets: { children: TreeItem[]; count: number };
  backend: { children: TreeItem[]; count: number };
  components: { children: TreeItem[]; count: number };
};

const DEFAULT_EXPANDED_IDS = ['group:pages', 'group:routes', 'group:components'];

async function backend<T>(body: Record<string, unknown>): Promise<T> {
  const response = await fetch('/api/apps/website-studio/backend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!response.ok) throw new Error('backend request failed');
  return response.json() as Promise<T>;
}

function WebsiteSitemapSidebarWidget() {
  const [sites, setSites] = useState<Site[]>([]);
  const [pages, setPages] = useState<BackendPage[]>([]);
  const [routes, setRoutes] = useState<BackendRoute[]>([]);
  const [assets, setAssets] = useState<BackendAsset[]>([]);
  const [siteStatus, setSiteStatus] = useState<Record<string, unknown> | null>(null);
  const [changeHistory, setChangeHistory] = useState<ChangesPayload | null>(null);
  const [changedPaths, setChangedPaths] = useState<Set<string>>(() => new Set());
  const [activeSiteId, setActiveSiteId] = useState('');
  const [selectedNodeId, setSelectedNodeId] = useState('');
  const [query, setQuery] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');

  const filteredSites = useMemo(() => sites.filter((site) => site.status !== 'archived'), [sites]);
  const treeItems = useMemo(
    () => activeSiteId ? filterTree(buildTree(pages, routes, assets, siteStatus, changeHistory, changedPaths), query.trim().toLowerCase()) : [],
    [activeSiteId, assets, changedPaths, changeHistory, pages, query, routes, siteStatus]
  );
  const defaultExpandedIds = useMemo(() => collectDefaultExpandedIds(treeItems, Boolean(query.trim())), [query, treeItems]);
  const treeProviderKey = `${activeSiteId || 'site'}:${query.trim().toLowerCase() || 'tree'}`;

  async function load(nextSiteId = activeSiteId) {
    setIsLoading(true);
    const sitePayload = await backend<{ items?: Site[] }>({ action: 'sites_list' });
    const nextSites = sitePayload.items || [];
    setSites(nextSites);
    const selectableSites = nextSites.filter((item) => item.status !== 'archived');
    const site = selectableSites.find((item) => item.id === nextSiteId);
    if (!site?.id) {
      setPages([]);
      setRoutes([]);
      setAssets([]);
      setActiveSiteId('');
      setSiteStatus(null);
      setChangeHistory(null);
      setChangedPaths(new Set());
      setError('');
      setIsLoading(false);
      return;
    }
    setActiveSiteId(site.id);
    const [map, statusPayload, changesPayload] = await Promise.all([
      backend<SitemapPayload>({ action: 'sitemap', site_id: site.id }),
      backend<Record<string, unknown>>({ action: 'site_status', site_id: site.id }),
      backend<ChangesPayload>({ action: 'list_changes', site_id: site.id })
    ]);
    setPages(map.items || []);
    setRoutes(map.routes || []);
    setAssets(map.assets || []);
    setSiteStatus(statusPayload || null);
    setChangeHistory(changesPayload || null);
    setChangedPaths(new Set((changesPayload?.working_diff || []).map((item) => String(item.path || '')).filter(Boolean)));
    setError('');
    setIsLoading(false);
  }

  useEffect(() => {
    load().catch((loadError: Error) => {
      setError(loadError.message || 'Sitemap unavailable.');
      setIsLoading(false);
    });
  }, []);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') return;
      const payload = event.data as { context?: { content?: { payload?: { active_app_params?: Record<string, string> } } }; owner_app_id?: string; type?: string };
      if (payload.type === 'maverick.widget.data-changed' && payload.owner_app_id === 'website-studio') {
        load(activeSiteId).catch((loadError: Error) => setError(loadError.message || 'Sitemap unavailable.'));
        return;
      }
      if (payload.type !== 'maverick.widget.context-changed') return;
      const params = payload.context?.content?.payload?.active_app_params || {};
      if (params.site_id && params.site_id !== activeSiteId) {
        load(String(params.site_id)).catch((loadError: Error) => setError(loadError.message || 'Sitemap unavailable.'));
      }
    }
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [activeSiteId]);

  async function selectSite(siteId: string) {
    setActiveSiteId(siteId);
    if (!siteId) {
      setPages([]);
      setRoutes([]);
      setAssets([]);
      setSiteStatus(null);
      setChangeHistory(null);
      setChangedPaths(new Set());
      setSelectedNodeId('');
      setError('');
      return;
    }
    if (siteId) {
      await backend({ action: 'site_set_active', site_id: siteId }).catch(() => null);
    }
    window.parent?.postMessage({ type: 'maverick.widget.open-app', app_id: 'website-studio', params: { site_id: siteId } }, window.location.origin);
    await load(siteId);
  }

  function selectNode(node: TreeItem) {
    setSelectedNodeId(node.id);
    if (node.empty || !node.kind || !node.entityId) return;
    openNode(node, activeSiteId);
  }

  return (
    <main className="website-studio-sitemap-widget">
      <label className="website-studio-sitemap-search">
        <span className="website-studio-sitemap-search-icon" aria-hidden="true" />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search site tree" />
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
          <p className="website-studio-sitemap-empty">{filteredSites.length ? 'Select a site to load its sitemap.' : 'No active websites yet.'}</p>
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
        ) : <p className="website-studio-sitemap-empty">No matching site items.</p>}
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
        <TreeExpander hasChildren={hasChildren} />
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

function buildTree(pages: BackendPage[], routes: BackendRoute[], assets: BackendAsset[], siteStatus: Record<string, unknown> | null, changeHistory: ChangesPayload | null, changedPaths: Set<string>): TreeItem[] {
  const pageNodes: TreeItem[] = pages
    .slice()
    .sort((left, right) => String(left.route || '').localeCompare(String(right.route || '')))
    .map((page) => {
      const changed = itemChanged(page, changedPaths);
      return {
        id: `page:${page.id}`,
        kind: 'page',
        entityId: String(page.id || ''),
        pageId: String(page.id || ''),
        route: String(page.route || ''),
        label: String(page.route || page.title || page.id),
        subtitle: String(page.title || 'static page'),
        status: changed ? 'modified' : page.warnings?.length ? 'warning' : '',
        warning: Boolean(page.warnings?.length),
        changed
      };
    });
  if (!pageNodes.length) pageNodes.push(emptyNode('No static HTML pages', 'source tree has no .html files'));

  const pageRouteIds = new Set(pages.map((page) => String(page.id || '')));
  const routeNodes: TreeItem[] = routes
    .filter((route) => !route.page_id || !pageRouteIds.has(String(route.page_id)))
    .slice()
    .sort((left, right) => String(left.route || '').localeCompare(String(right.route || '')))
    .map((route) => {
      const changed = itemChanged(route, changedPaths);
      return {
        id: `route:${route.id}`,
        kind: 'route',
        entityId: String(route.id || ''),
        routeId: String(route.id || ''),
        route: String(route.route || ''),
        label: String(route.route || route.id),
        subtitle: String(route.kind || 'route'),
        status: changed ? 'modified' : route.page_id ? String(route.status || '') : 'no html',
        warning: Boolean(!route.page_id || route.warnings?.length || route.status === 'broken' || route.status === 'unmatched'),
        changed
      };
    });
  if (!routeNodes.length) routeNodes.push(emptyNode('No sitemap-only routes', 'all routes map to pages'));

  const assetBuckets = bucketAssets(assets, changedPaths);
  return [
    groupNode('group:pages', 'Pages', `${pages.length} static`, pageNodes),
    groupNode('group:routes', 'Sitemap routes', `${routeNodes.filter((node) => !node.empty).length} checked`, routeNodes),
    groupNode('group:components', 'Components', `${assetBuckets.components.count} files`, assetBuckets.components.children),
    groupNode('group:assets', 'Assets', `${assetBuckets.assets.count} files`, assetBuckets.assets.children),
    groupNode('group:backend', 'Backend and config', `${assetBuckets.backend.count} files`, assetBuckets.backend.children),
    groupNode('group:status', 'Status', `${String(siteStatus?.runtime_status || 'unknown')} | ${changedPaths.size} changed`, [statusNode(siteStatus, changeHistory, changedPaths)])
  ];
}

function groupNode(id: string, label: string, subtitle: string, children: TreeItem[]): TreeItem {
  return { id, kind: 'group', label, subtitle, status: String(children.filter((child) => !child.empty).length), children };
}

function emptyNode(label: string, subtitle: string): TreeItem {
  return { id: `empty:${label}`, kind: 'empty', label, subtitle, status: 'empty', empty: true };
}

function bucketAssets(sourceAssets: BackendAsset[], changedPaths: Set<string>): AssetBuckets {
  const buckets: AssetBuckets = {
    components: { count: 0, children: [] },
    assets: { count: 0, children: [] },
    backend: { count: 0, children: [] }
  };
  for (const asset of sourceAssets) {
    const path = String(asset.path || '');
    const category = assetCategory(path, String(asset.kind || 'file'));
    buckets[category].count += 1;
    const changed = itemChanged(asset, changedPaths);
    addPathNode(buckets[category].children, path, {
      id: `asset:${asset.id}`,
      kind: 'asset',
      entityId: String(asset.id || ''),
      assetId: String(asset.id || ''),
      label: basename(path),
      subtitle: dirname(path) || String(asset.kind || 'file'),
      status: changed ? 'modified' : '',
      warning: Boolean(asset.warnings?.length),
      changed
    });
  }
  for (const bucket of Object.values(buckets)) {
    if (!bucket.children.length) bucket.children.push(emptyNode('No files', ''));
    sortNodes(bucket.children);
  }
  return buckets;
}

function statusNode(siteStatus: Record<string, unknown> | null, changeHistory: ChangesPayload | null, changedPaths: Set<string>): TreeItem {
  const latestBuild = (changeHistory?.builds || [])[0] || {};
  const latestRequest = (changeHistory?.publish_requests || [])[0] || {};
  return {
    id: 'status:summary',
    kind: 'status',
    label: String(siteStatus?.runtime_status || 'unknown').replace('_', ' '),
    subtitle: `build ${String(latestBuild.status || 'none')} | requests ${String(latestRequest.status || 'none')}`,
    status: changedPaths.size ? `${changedPaths.size} modified` : 'clean',
    changed: Boolean(changedPaths.size)
  };
}

function itemChanged(item: { path?: string; source_files?: string[] } | null | undefined, changedPaths: Set<string>) {
  if (!item || !changedPaths.size) return false;
  const directPath = String(item.path || '');
  if (directPath && changedPaths.has(directPath)) return true;
  return (item.source_files || []).some((path) => changedPaths.has(String(path || '')));
}

function assetCategory(path: string, kind: string): keyof AssetBuckets {
  const lower = path.toLowerCase();
  if (lower.startsWith('frontend-website/src/') || lower.startsWith('src/') || lower.includes('/components/') || lower.endsWith('.scss')) return 'components';
  if (['image', 'font', 'media', 'stylesheet', 'script'].includes(kind) && !lower.endsWith('.php')) return 'assets';
  if (/\.(png|jpe?g|gif|webp|svg|ico|avif|mp4|webm|mp3|woff2?|ttf|css|js)$/i.test(path)) return 'assets';
  return 'backend';
}

function addPathNode(children: TreeItem[], path: string, leaf: TreeItem) {
  const parts = path.split('/').filter(Boolean);
  let currentChildren = children;
  let currentPath = '';
  for (let index = 0; index < parts.length - 1; index += 1) {
    const part = parts[index];
    currentPath = currentPath ? `${currentPath}/${part}` : part;
    let folder = currentChildren.find((node) => node.kind === 'folder' && node.route === currentPath);
    if (!folder) {
      folder = { id: `folder:${currentPath}`, kind: 'folder', route: currentPath, label: part, subtitle: currentPath, status: '', children: [] };
      currentChildren.push(folder);
    }
    currentChildren = folder.children || [];
  }
  currentChildren.push(leaf);
}

function sortNodes(nodes: TreeItem[]) {
  nodes.sort((left, right) => {
    if (Boolean(left.children?.length) !== Boolean(right.children?.length)) return left.children?.length ? -1 : 1;
    return String(left.label).localeCompare(String(right.label));
  });
  nodes.forEach((node) => node.children && sortNodes(node.children));
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
  return `${node.label || ''} ${node.subtitle || ''} ${node.status || ''}`.toLowerCase().includes(needle);
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

function openNode(node: TreeItem, activeSiteId: string) {
  if (!node || node.empty || !node.kind || !node.entityId) return;
  const kind = node.kind;
  const id = node.entityId;
  const params: Record<string, string> = { site_id: activeSiteId, app_page: `${kind}s/${id}` };
  if (kind === 'page') {
    params.page_id = node.pageId || id;
    params.route = node.route || '';
  }
  if (kind === 'route') {
    params.route_id = node.routeId || id;
    params.route = node.route || '';
  }
  if (kind === 'asset') {
    params.asset_id = node.assetId || id;
  }
  window.parent?.postMessage({ type: 'maverick.widget.open-app', app_id: 'website-studio', params }, window.location.origin);
  window.parent?.postMessage({ type: 'maverick.shell.sidebar.close' }, window.location.origin);
}

function basename(path: string) {
  return path.split('/').filter(Boolean).pop() || path || '/';
}

function dirname(path: string) {
  const parts = path.split('/').filter(Boolean);
  parts.pop();
  return parts.join('/');
}

function WebsiteTreeSkeleton() {
  return (
    <div className="website-studio-sitemap-skeleton" role="status" aria-label="Website sitemap is loading">
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
