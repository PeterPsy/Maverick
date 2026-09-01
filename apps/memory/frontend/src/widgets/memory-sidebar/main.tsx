import { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Search } from "lucide-react";
import { colors } from "../../constants";
import { labelForType, truncate } from "../../format";
import { NodeTypeIcon } from "../../components/nodeIcons";
import { useShellSidebarCloseSwipe } from "../../hooks/useShellSidebarCloseSwipe";
import { nodeIdFromSelectionMessage, nodeIdFromWidgetContext, type ActiveMemorySelectionMessage } from "../../lib/activeMemorySelection";
import { callMemory, currentMemoryAppId, MemoryApiError, normalizeViewFilter } from "../../memoryApi";
import type { GraphNode, ViewFilter } from "../../types";
import "../../styles/sidebar-widget.css";

const MOBILE_LAYOUT_QUERY = "(max-width: 979px)";

type GraphPayload = {
  nodes?: GraphNode[];
};

function isMobileLayoutViewport() {
  if (typeof window === "undefined") {
    return false;
  }
  try {
    const shellWindow = window.parent && window.parent !== window ? window.parent : window;
    return typeof shellWindow.matchMedia === "function" && shellWindow.matchMedia(MOBILE_LAYOUT_QUERY).matches;
  } catch {
    return typeof window.matchMedia === "function" && window.matchMedia(MOBILE_LAYOUT_QUERY).matches;
  }
}

function useShellMobileLayout() {
  const [isShellMobileLayout, setIsShellMobileLayout] = useState(isMobileLayoutViewport);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    let mediaQuery: MediaQueryList;
    try {
      const shellWindow = window.parent && window.parent !== window ? window.parent : window;
      mediaQuery = shellWindow.matchMedia(MOBILE_LAYOUT_QUERY);
    } catch {
      mediaQuery = window.matchMedia(MOBILE_LAYOUT_QUERY);
    }
    const update = () => setIsShellMobileLayout(mediaQuery.matches);
    update();
    mediaQuery.addEventListener("change", update);
    return () => mediaQuery.removeEventListener("change", update);
  }, []);

  return isShellMobileLayout;
}

function openNodeInShell(nodeId: string, appId: string) {
  window.parent?.postMessage(
    {
      type: "maverick.widget.open-app",
      app_id: appId,
      params: {
        app_page: `nodes/${encodeURIComponent(nodeId)}`,
        node_id: nodeId,
      },
    },
    "*",
  );
  if (isMobileLayoutViewport()) {
    window.parent?.postMessage({ type: "maverick.shell.sidebar.close" }, "*");
  }
}

function nodeMatchesSearch(node: GraphNode, query: string) {
  if (!query) return true;
  return `${node.title} ${node.summary} ${node.body_text} ${node.type} ${node.id}`.toLowerCase().includes(query);
}

function graphRequest(viewFilter: ViewFilter, query: string) {
  const body: Record<string, unknown> = { action: "graph", query, limit: 160 };
  if (viewFilter.mode === "custom") {
    body.node_ids = viewFilter.refs.map((ref) => ref.entity_id).filter(Boolean);
  }
  return body;
}

function graphRequestKey(viewFilter: ViewFilter, query: string) {
  const refs = viewFilter.mode === "custom" ? viewFilter.refs.map((ref) => ref.entity_id).join(",") : "";
  return `${viewFilter.mode}:${query}:${refs}`;
}

function MemorySidebarWidget() {
  const appId = useMemo(() => currentMemoryAppId(), []);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [query, setQuery] = useState("");
  const [viewFilter, setViewFilter] = useState<ViewFilter>(() => normalizeViewFilter());
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isShellMobileLayout = useShellMobileLayout();
  const graphAbortRef = useRef<AbortController | null>(null);
  const graphRequestSeqRef = useRef(0);
  const hasLoadedViewStateRef = useRef(false);
  const queryRef = useRef("");
  const skipGraphEffectKeyRef = useRef("");

  useShellSidebarCloseSwipe(isShellMobileLayout);

  const filteredNodes = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return nodes.filter((node) => nodeMatchesSearch(node, needle));
  }, [nodes, query]);

  useEffect(() => {
    queryRef.current = query;
  }, [query]);

  async function refreshViewFilter() {
    const payload = await callMemory<{ state?: { view_filter?: ViewFilter } }>({ action: "view_filter" });
    const next = normalizeViewFilter(payload.state?.view_filter);
    hasLoadedViewStateRef.current = true;
    setViewFilter(next);
    setQuery(next.mode === "custom" ? next.query : "");
    return next;
  }

  async function refreshGraph(nextViewFilter = viewFilter, nextQuery = query.trim()) {
    graphAbortRef.current?.abort();
    const controller = new AbortController();
    graphAbortRef.current = controller;
    const requestId = graphRequestSeqRef.current + 1;
    graphRequestSeqRef.current = requestId;
    let payload: GraphPayload;
    try {
      payload = await callMemory<GraphPayload>(graphRequest(nextViewFilter, nextQuery), { signal: controller.signal });
    } catch (loadError) {
      if (loadError instanceof MemoryApiError && loadError.code === "request_cancelled") {
        return;
      }
      throw loadError;
    }
    if (controller.signal.aborted || requestId !== graphRequestSeqRef.current) {
      return;
    }
    const nextNodes = payload.nodes || [];
    setNodes(nextNodes);
    setSelectedNodeId((current) => {
      if (current && nextNodes.some((node) => node.id === current)) {
        return current;
      }
      return current || nextNodes[0]?.id || "";
    });
  }

  async function refreshAll() {
    try {
      const next = await refreshViewFilter();
      const nextQuery = next.mode === "custom" ? next.query : "";
      skipGraphEffectKeyRef.current = graphRequestKey(next, nextQuery);
      await refreshGraph(next, nextQuery);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load memory.");
    } finally {
      setIsInitialLoading(false);
    }
  }

  useEffect(() => {
    void refreshAll();
  }, []);

  useEffect(() => {
    if (!hasLoadedViewStateRef.current) {
      return;
    }
    const nextQuery = query.trim();
    const requestKey = graphRequestKey(viewFilter, nextQuery);
    if (skipGraphEffectKeyRef.current === requestKey) {
      skipGraphEffectKeyRef.current = "";
      return;
    }
    const timeout = window.setTimeout(() => {
      refreshGraph(viewFilter, nextQuery)
        .then(() => setError(null))
        .catch((searchError: Error) => setError(searchError.message));
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [query, viewFilter]);

  useEffect(() => {
    return () => graphAbortRef.current?.abort();
  }, []);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as {
        owner_app_id?: string;
        resource?: string;
        type?: string;
      } & ActiveMemorySelectionMessage;
      const contextNodeId = nodeIdFromWidgetContext(payload, appId);
      if (contextNodeId) {
        setSelectedNodeId(contextNodeId);
        return;
      }
      const activeNodeId = nodeIdFromSelectionMessage(payload, appId);
      if (activeNodeId) {
        setSelectedNodeId(activeNodeId);
        return;
      }
      if (payload.type !== "maverick.widget.data-changed" || payload.owner_app_id !== appId) {
        return;
      }
      if (payload.resource === "view-state") {
        void refreshAll();
      } else if (payload.resource === "graph") {
        void refreshGraph(viewFilter, queryRef.current.trim());
      }
    }

    window.addEventListener("message", handleShellMessage);
    return () => window.removeEventListener("message", handleShellMessage);
  }, [appId, viewFilter]);

  async function clearCustomView() {
    try {
      const payload = await callMemory<{ state?: { view_filter?: ViewFilter } }>({ action: "clear_custom_view" });
      const next = normalizeViewFilter(payload.state?.view_filter);
      skipGraphEffectKeyRef.current = graphRequestKey(next, "");
      setViewFilter(next);
      setQuery("");
      await refreshGraph(next, "");
      setError(null);
    } catch (clearError) {
      setError(clearError instanceof Error ? clearError.message : "Unable to clear custom view.");
    }
  }

  function selectNode(node: GraphNode) {
    setSelectedNodeId(node.id);
    openNodeInShell(node.id, appId);
  }

  return (
    <main className={`memory-sidebar-widget ${isShellMobileLayout ? "is-shell-mobile" : ""}`}>
      <div className="memory-sidebar-search-frame">
        <Search size={17} aria-hidden="true" />
        <input
          aria-label="Search memory"
          className="memory-sidebar-search"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search memory"
          value={query}
        />
      </div>

      {error ? <p className="memory-sidebar-empty">{error}</p> : null}

      <div className="memory-sidebar-list">
        {viewFilter.mode === "custom" ? (
          <div className="memory-sidebar-custom-view">
            <span>
              <strong>{viewFilter.title || "Custom view"}</strong>
              <small>{viewFilter.refs.length} curated node{viewFilter.refs.length === 1 ? "" : "s"}</small>
            </span>
            <button onClick={clearCustomView} type="button">Full graph</button>
          </div>
        ) : null}

        {isInitialLoading ? (
          <MemorySidebarSkeleton />
        ) : filteredNodes.length ? (
          filteredNodes.slice(0, 48).map((node) => {
            const color = colors[node.type] || "#ccd6dd";
            return (
              <button
                className={`memory-sidebar-row ${node.id === selectedNodeId ? "is-active" : ""}`}
                key={node.id}
                onClick={() => selectNode(node)}
                type="button"
              >
                <span className="memory-sidebar-row__icon" style={{ color }} aria-hidden="true">
                  <NodeTypeIcon type={node.type} size={17} />
                  <i style={{ background: color }} />
                </span>
                <span className="memory-sidebar-row__copy">
                  <strong>{node.title}</strong>
                  <span>{labelForType(node.type)} · {truncate(node.summary || node.body_text, 52)}</span>
                </span>
              </button>
            );
          })
        ) : (
          <p className="memory-sidebar-empty">No memory nodes found.</p>
        )}
      </div>
    </main>
  );
}

function MemorySidebarSkeleton() {
  return (
    <div aria-hidden="true" className="memory-sidebar-skeleton">
      {Array.from({ length: 6 }).map((_, index) => (
        <div className="memory-sidebar-skeleton__row" key={index}>
          <span className="memory-sidebar-skeleton__icon" />
          <span className="memory-sidebar-skeleton__copy">
            <span />
            <span />
          </span>
        </div>
      ))}
    </div>
  );
}

createRoot(document.getElementById("memory-sidebar-root") as HTMLElement).render(<MemorySidebarWidget />);
