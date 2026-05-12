import { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrainCircuit, Search } from "lucide-react";
import { colors } from "../../constants";
import { labelForType, truncate } from "../../format";
import { useShellSidebarCloseSwipe } from "../../hooks/useShellSidebarCloseSwipe";
import { nodeIdFromSelectionMessage, nodeIdFromWidgetContext, type ActiveMemorySelectionMessage } from "../../lib/activeMemorySelection";
import { callMemory, normalizeViewFilter } from "../../memoryApi";
import type { GraphEdge, GraphNode, ViewFilter } from "../../types";
import "../../styles/sidebar-widget.css";

const MOBILE_LAYOUT_QUERY = "(max-width: 979px)";

type GraphPayload = {
  edges?: GraphEdge[];
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

function openNodeInShell(nodeId: string) {
  window.parent?.postMessage(
    {
      type: "maverick.widget.open-app",
      app_id: "memory",
      params: {
        app_page: `nodes/${encodeURIComponent(nodeId)}`,
        node_id: nodeId,
      },
    },
    window.location.origin,
  );
  if (isMobileLayoutViewport()) {
    window.parent?.postMessage({ type: "maverick.shell.sidebar.close" }, window.location.origin);
  }
}

function nodeMatchesSearch(node: GraphNode, query: string) {
  if (!query) return true;
  return `${node.title} ${node.summary} ${node.body_text} ${node.type} ${node.id}`.toLowerCase().includes(query);
}

function graphRequest(viewFilter: ViewFilter) {
  const body: Record<string, unknown> = { action: "graph", query: viewFilter.query, limit: 160 };
  if (viewFilter.mode === "custom") {
    body.node_ids = viewFilter.refs.map((ref) => ref.entity_id).filter(Boolean);
  }
  return body;
}

function MemorySidebarWidget() {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [query, setQuery] = useState("");
  const [viewFilter, setViewFilter] = useState<ViewFilter>(() => normalizeViewFilter());
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [contextText, setContextText] = useState("");
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isShellMobileLayout = useShellMobileLayout();
  const lastPersistedQueryRef = useRef("");
  const hasLoadedViewStateRef = useRef(false);

  useShellSidebarCloseSwipe(isShellMobileLayout);

  const filteredNodes = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return nodes.filter((node) => nodeMatchesSearch(node, needle));
  }, [nodes, query]);

  async function refreshViewFilter() {
    const payload = await callMemory<{ state?: { view_filter?: ViewFilter } }>({ action: "view_filter" });
    const next = normalizeViewFilter(payload.state?.view_filter);
    lastPersistedQueryRef.current = next.query;
    hasLoadedViewStateRef.current = true;
    setViewFilter(next);
    setQuery(next.query);
    return next;
  }

  async function refreshGraph(nextViewFilter = viewFilter) {
    const payload = await callMemory<GraphPayload>(graphRequest(nextViewFilter));
    const nextNodes = payload.nodes || [];
    setNodes(nextNodes);
    setEdges(payload.edges || []);
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
      await refreshGraph(next);
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
    if (!hasLoadedViewStateRef.current || query === lastPersistedQueryRef.current) {
      return;
    }
    const timeout = window.setTimeout(() => {
      const nextQuery = query.trim();
      callMemory<{ state?: { view_filter?: ViewFilter } }>({ action: "set_view_filter", query: nextQuery })
        .then((payload) => {
          const next = normalizeViewFilter(payload.state?.view_filter);
          lastPersistedQueryRef.current = next.query;
          setViewFilter(next);
          setError(null);
          return refreshGraph(next);
        })
        .catch((saveError: Error) => setError(saveError.message));
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [query]);

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
      const contextNodeId = nodeIdFromWidgetContext(payload);
      if (contextNodeId) {
        setSelectedNodeId(contextNodeId);
        return;
      }
      const activeNodeId = nodeIdFromSelectionMessage(payload);
      if (activeNodeId) {
        setSelectedNodeId(activeNodeId);
        return;
      }
      if (payload.type !== "maverick.widget.data-changed" || payload.owner_app_id !== "memory") {
        return;
      }
      if (payload.resource === "view-state") {
        void refreshAll();
      } else if (payload.resource === "graph") {
        void refreshGraph();
      }
    }

    window.addEventListener("message", handleShellMessage);
    return () => window.removeEventListener("message", handleShellMessage);
  }, [viewFilter]);

  async function previewContext() {
    try {
      const payload = await callMemory<{ items?: Array<{ title: string; summary?: string; body_text?: string; type?: string }> }>({
        action: "context",
        query,
        limit: 5,
      });
      const lines = (payload.items || []).map((item) => {
        const body = item.summary || item.body_text || "";
        return `${item.title} - ${labelForType(item.type || "note")}: ${truncate(body, 120)}`;
      });
      setContextText(lines.length ? lines.join("\n\n") : "No matching context.");
      setError(null);
    } catch (contextError) {
      setError(contextError instanceof Error ? contextError.message : "Unable to preview context.");
    }
  }

  async function clearCustomView() {
    try {
      const payload = await callMemory<{ state?: { view_filter?: ViewFilter } }>({ action: "clear_custom_view" });
      const next = normalizeViewFilter(payload.state?.view_filter);
      lastPersistedQueryRef.current = next.query;
      setViewFilter(next);
      setQuery(next.query);
      await refreshGraph(next);
      setError(null);
    } catch (clearError) {
      setError(clearError instanceof Error ? clearError.message : "Unable to clear custom view.");
    }
  }

  function selectNode(node: GraphNode) {
    setSelectedNodeId(node.id);
    openNodeInShell(node.id);
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

        <div className="memory-sidebar-stats" aria-label="Memory graph stats">
          <span>{nodes.length}<small>nodes</small></span>
          <span>{edges.length}<small>links</small></span>
        </div>

        {isInitialLoading ? (
          <MemorySidebarSkeleton />
        ) : filteredNodes.length ? (
          filteredNodes.slice(0, 48).map((node) => (
            <button
              className={`memory-sidebar-row ${node.id === selectedNodeId ? "is-active" : ""}`}
              key={node.id}
              onClick={() => selectNode(node)}
              type="button"
            >
              <span className="memory-sidebar-row__icon" aria-hidden="true">
                <BrainCircuit size={17} />
                <i style={{ background: colors[node.type] || "#ccd6dd" }} />
              </span>
              <span className="memory-sidebar-row__copy">
                <strong>{node.title}</strong>
                <span>{labelForType(node.type)} · {truncate(node.summary || node.body_text, 52)}</span>
              </span>
            </button>
          ))
        ) : (
          <p className="memory-sidebar-empty">No memory nodes found.</p>
        )}

        <section className="memory-sidebar-context">
          <button className="memory-sidebar-context-button" onClick={previewContext} type="button">
            Preview context
          </button>
          {contextText ? <pre>{contextText}</pre> : null}
        </section>
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
