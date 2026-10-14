import { connectAppEventSocket, isExactLoopinoParentMessage } from '@loopino/pwa-cache';
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CreateNodeModal } from "./components/CreateNodeModal";
import { GraphCanvas } from "./components/GraphCanvas";
import { PreviewContextModal, type PreviewContextItem } from "./components/PreviewContextModal";
import { useMemoryExploration } from "./hooks/useMemoryExploration";
import { nodeIdFromParams, scalarString, shouldOpenCreateNode, shouldOpenPreviewContext } from "./lib/memoryNavigationParams";
import { callMemory, currentMemoryAppId, MemoryApiError, normalizeViewFilter } from "./memoryApi";
import { contextIdsFromParams, mergeSubgraph, type Subgraph } from "./lib/graphSubgraph";
import type { GraphEdge, GraphNode, NodeDraft, ViewFilter } from "./types";

const defaultDraft = { title: "", body: "", type: "note" };

type LoadViewFilterOptions = {
  signal?: AbortSignal;
};

export function MemoryApp() {
  const appId = useMemo(() => currentMemoryAppId(), []);
  const eventRefreshTimerRef = useRef<number | null>(null);
  const graphAbortRef = useRef<AbortController | null>(null);
  const graphRequestSeqRef = useRef(0);
  const nodesRef = useRef<GraphNode[]>([]);
  const edgesRef = useRef<GraphEdge[]>([]);
  const previewAbortRef = useRef<AbortController | null>(null);
  const previewRequestSeqRef = useRef(0);
  const viewFilterRequestSeqRef = useRef(0);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [query, setQuery] = useState("");
  const [viewFilter, setViewFilter] = useState<ViewFilter>(() => normalizeViewFilter());
  const [draft, setDraft] = useState<NodeDraft>(defaultDraft);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [creatingNode, setCreatingNode] = useState(false);
  const [graphLoading, setGraphLoading] = useState(true);
  const [previewContextOpen, setPreviewContextOpen] = useState(false);
  const [previewContextLoading, setPreviewContextLoading] = useState(false);
  const [previewContextItems, setPreviewContextItems] = useState<PreviewContextItem[]>([]);
  const [previewContextQuery, setPreviewContextQuery] = useState("");
  const [previewContextSnapshot, setPreviewContextSnapshot] = useState("");
  const [previewContextError, setPreviewContextError] = useState("");
  const [error, setError] = useState("");
  const consumedCreateRequests = useRef<Set<string>>(new Set());
  const consumedPreviewRequests = useRef<Set<string>>(new Set());
  const consumedLegacyCreateRequest = useRef(false);
  const consumedLegacyPreviewRequest = useRef(false);
  const focusedGraphRef = useRef<Subgraph | null>(null);
  const localContextRef = useRef<string[] | null>(null);
  const [contextSnapshot, setContextSnapshot] = useState("");

  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);

  const hydrateGraph = useCallback((payload: { nodes?: GraphNode[]; edges?: GraphEdge[] }) => {
    const graph = mergeSubgraph({ nodes: payload.nodes || [], edges: payload.edges || [] }, focusedGraphRef.current);
    // Navigation can continue before React commits the graph render.
    nodesRef.current = graph.nodes;
    edgesRef.current = graph.edges;
    setNodes(graph.nodes);
    setEdges(graph.edges);
  }, []);

  const { selectedId, selectedDetails, selectedIdRef, selectNode, moreConnections, goBack, canGoBack, relationships, connectionCursor, connectionLoading } =
    useMemoryExploration({ appId, focusedGraphRef, nodesRef, edgesRef, hydrateGraph, setError });
  const selectedNode = selectedId ? nodeById.get(selectedId) || selectedDetails || null : null;

  const refreshGraph = useCallback(async (override: { query: string; viewFilter: ViewFilter }) => {
    setGraphLoading(true);
    const effectiveQuery = override.query;
    const effectiveViewFilter = override.viewFilter;
    const body: Record<string, unknown> = { action: "graph", query: effectiveQuery, limit: 30 };
    if (localContextRef.current) {
      body.node_ids = localContextRef.current;
      body.query = "";
      body.limit = Math.max(1, Math.min(40, localContextRef.current.length));
    } else if (effectiveViewFilter.mode === "custom") {
      body.node_ids = effectiveViewFilter.refs.map((ref) => ref.entity_id).filter(Boolean);
    }
    graphAbortRef.current?.abort();
    const controller = new AbortController();
    graphAbortRef.current = controller;
    const requestId = graphRequestSeqRef.current + 1;
    graphRequestSeqRef.current = requestId;
    let payload: { nodes?: GraphNode[]; edges?: GraphEdge[] };
    try {
      payload = await callMemory<{ nodes?: GraphNode[]; edges?: GraphEdge[] }>(body, { signal: controller.signal });
    } catch (loadError) {
      if (isCancelledRequest(loadError)) {
        return;
      }
      if (requestId === graphRequestSeqRef.current) {
        setGraphLoading(false);
      }
      throw loadError;
    }
    if (controller.signal.aborted || requestId !== graphRequestSeqRef.current) {
      return;
    }
    hydrateGraph(payload);
    setGraphLoading(false);
  }, [hydrateGraph]);

  const readViewFilter = useCallback(async (options: LoadViewFilterOptions = {}) => {
    const payload = await callMemory<{ state?: { view_filter?: ViewFilter } }>({ action: "view_filter" }, { signal: options.signal });
    const next = normalizeViewFilter(payload.state?.view_filter);
    if (options.signal?.aborted) {
      throw new MemoryApiError("Memory request was cancelled.", { code: "request_cancelled" });
    }
    return next;
  }, []);

  const loadViewFilter = useCallback(async (options: LoadViewFilterOptions = {}) => {
    const requestId = viewFilterRequestSeqRef.current + 1;
    viewFilterRequestSeqRef.current = requestId;
    const next = await readViewFilter(options);
    if (requestId !== viewFilterRequestSeqRef.current) {
      throw new MemoryApiError("Memory request was cancelled.", { code: "request_cancelled" });
    }
    setViewFilter(next);
    setQuery(next.query || "");
    return next;
  }, [readViewFilter]);


  const refreshMemory = useCallback(() => {
    setGraphLoading(true);
    loadViewFilter()
      .then((next) => refreshGraph({ query: next.query, viewFilter: next }))
      .catch((loadError) => {
        if (!isCancelledRequest(loadError)) {
          setGraphLoading(false);
          setError(loadError instanceof Error ? loadError.message : "Unable to load memory.");
        }
      });
  }, [loadViewFilter, refreshGraph]);

  useEffect(() => {
    refreshMemory();
  }, [refreshMemory]);

  const scheduleEventRefresh = useCallback(() => {
    if (eventRefreshTimerRef.current !== null) window.clearTimeout(eventRefreshTimerRef.current);
    eventRefreshTimerRef.current = window.setTimeout(() => {
      eventRefreshTimerRef.current = null;
      refreshMemory();
      if (selectedIdRef.current) void selectNode(selectedIdRef.current);
    }, 250);
  }, [refreshMemory, selectNode]);

  useEffect(() => {
    return () => {
      if (eventRefreshTimerRef.current !== null) window.clearTimeout(eventRefreshTimerRef.current);
      graphAbortRef.current?.abort();
      previewAbortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    window.parent?.postMessage({ type: "loopino.app.ready", app_id: appId }, "*");
  }, [appId]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (!isExactLoopinoParentMessage(event) || !event.data || typeof event.data !== "object") return;
      const payload = event.data as {
        app_id?: string;
        owner_app_id?: string;
        params?: Record<string, string | boolean | null>;
        resource?: string;
        type?: string;
      };
      if (payload.type === "loopino.app.navigate" && (!payload.app_id || payload.app_id === appId)) {
        void handleNavigationParams(payload.params || {});
        return;
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [appId, scheduleEventRefresh]);

  useEffect(() => connectAppEventSocket<{ type?: string; owner_app_id?: string }>((payload) => {
    if (payload.type === 'loopino.app.data-changed' && payload.owner_app_id === appId) scheduleEventRefresh();
  }, scheduleEventRefresh), [appId, scheduleEventRefresh]);



  async function remember() {
    setCreatingNode(true);
    setError("");
    try {
      const payload = await callMemory<{ node?: GraphNode }>({
        action: "remember",
        title: draft.title,
        body: draft.body,
        type: draft.type,
      });
      if (!payload.node?.id) {
        throw new Error("Memory backend did not return a created node.");
      }
      setDraft({ ...defaultDraft, type: draft.type });
      setCreateModalOpen(false);
      await refreshGraph({ query, viewFilter });
      await selectNode(payload.node.id);
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "Unable to create node.");
    } finally {
      setCreatingNode(false);
    }
  }

  async function openPreviewContext() {
    previewAbortRef.current?.abort();
    const controller = new AbortController();
    previewAbortRef.current = controller;
    const requestId = previewRequestSeqRef.current + 1;
    previewRequestSeqRef.current = requestId;
    setPreviewContextOpen(true);
    setPreviewContextLoading(true);
    setPreviewContextError("");
    setPreviewContextItems([]);
    try {
      const next = await readViewFilter({ signal: controller.signal });
      if (controller.signal.aborted || requestId !== previewRequestSeqRef.current) {
        return;
      }
      const contextQuery = next.query || "";
      setPreviewContextQuery(contextQuery);
      const payload = await callMemory<{ items?: PreviewContextItem[]; snapshot_id?: string }>({
        action: "context",
        query: contextQuery,
        limit: 5,
      }, { signal: controller.signal });
      if (controller.signal.aborted || requestId !== previewRequestSeqRef.current) {
        return;
      }
      setPreviewContextItems(payload.items || []);
      setPreviewContextSnapshot(payload.snapshot_id || "");
    } catch (contextError) {
      if (isCancelledRequest(contextError)) {
        return;
      }
      setPreviewContextError(contextError instanceof Error ? contextError.message : "Unable to preview context.");
    } finally {
      if (requestId === previewRequestSeqRef.current) {
        setPreviewContextLoading(false);
      }
    }
  }

  function closePreviewContext() {
    previewAbortRef.current?.abort();
    setPreviewContextLoading(false);
    setPreviewContextOpen(false);
  }

  async function handleNavigationParams(params: Record<string, string | boolean | null>) {
    const contextIds = contextIdsFromParams(params);
    if (contextIds.length) {
      localContextRef.current = contextIds;
      focusedGraphRef.current = null;
      setContextSnapshot(scalarString(params.context_snapshot_id) || "Referenced context");
      await refreshGraph({ query: "", viewFilter });
    }
    const requestedNodeId = nodeIdFromParams(params);
    if (requestedNodeId) {
      if (nodesRef.current.some((node) => node.id === requestedNodeId) || selectedIdRef.current !== requestedNodeId) {
        await selectNode(requestedNodeId);
      }
    }
    if (shouldOpenPreviewContext(params)) {
      const requestId = scalarString(params.preview_context_request_id);
      if (requestId) {
        if (consumedPreviewRequests.current.has(requestId)) {
          return;
        }
        consumedPreviewRequests.current.add(requestId);
      } else if (consumedLegacyPreviewRequest.current) {
        return;
      } else {
        consumedLegacyPreviewRequest.current = true;
      }
      await openPreviewContext();
      return;
    }
    if (!shouldOpenCreateNode(params)) {
      return;
    }
    const requestId = scalarString(params.new_node_request_id);
    if (requestId) {
      if (consumedCreateRequests.current.has(requestId)) {
        return;
      }
      consumedCreateRequests.current.add(requestId);
    } else if (consumedLegacyCreateRequest.current) {
      return;
    } else {
      consumedLegacyCreateRequest.current = true;
    }
    setCreateModalOpen(true);
  }

  return (
    <main className="memory-shell">
      {error ? <div className="memory-error" role="alert">{error}</div> : null}
      {contextSnapshot && <div className="memory-context-banner">Referenced context · {contextSnapshot.slice(0, 12)}
        <button type="button" onClick={() => { localContextRef.current = null; focusedGraphRef.current = null; setContextSnapshot(""); refreshMemory(); }}>Workspace view</button>
      </div>}
      <GraphCanvas
        nodes={nodes}
        edges={edges}
        selectedId={selectedId}
        selectedNode={selectedNode}
        selectedDetails={selectedDetails}
        loading={graphLoading}
        relationships={relationships}
        connectionsMore={!!connectionCursor}
        connectionsLoading={connectionLoading}
        onMoreConnections={() => void moreConnections()}
        onBack={canGoBack ? goBack : undefined}
        onSelectNode={(id) => void selectNode(id)}
      />
      <CreateNodeModal
        draft={draft}
        open={createModalOpen}
        saving={creatingNode}
        onClose={() => {
          if (!creatingNode) setCreateModalOpen(false);
        }}
        onCreate={remember}
        onDraftChange={setDraft}
      />
      <PreviewContextModal
        error={previewContextError}
        items={previewContextItems}
        loading={previewContextLoading}
        open={previewContextOpen}
        query={previewContextQuery}
        onClose={closePreviewContext}
        onSelect={(id) => { closePreviewContext(); void selectNode(id); }}
        onShowGraph={() => {
          localContextRef.current = previewContextItems.map((item) => item.node_id || "").filter(Boolean);
          focusedGraphRef.current = null; setContextSnapshot(previewContextSnapshot || "Preview context"); closePreviewContext();
          void refreshGraph({ query: "", viewFilter });
        }}
      />
    </main>
  );
}

function isCancelledRequest(error: unknown): boolean {
  return error instanceof MemoryApiError && error.code === "request_cancelled";
}
