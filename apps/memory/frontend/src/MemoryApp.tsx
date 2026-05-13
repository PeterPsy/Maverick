import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CreateNodeModal } from "./components/CreateNodeModal";
import { GraphCanvas } from "./components/GraphCanvas";
import { PreviewContextModal, type PreviewContextItem } from "./components/PreviewContextModal";
import { notifyActiveMemorySelection } from "./lib/activeMemorySelection";
import { nodeIdFromParams, scalarString, shouldOpenCreateNode, shouldOpenPreviewContext } from "./lib/memoryNavigationParams";
import { callMemory, currentMemoryAppId, MemoryApiError, normalizeViewFilter } from "./memoryApi";
import type { GraphEdge, GraphNode, NodeDetails, NodeDraft, ViewFilter } from "./types";

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
  const previewAbortRef = useRef<AbortController | null>(null);
  const previewRequestSeqRef = useRef(0);
  const selectAbortRef = useRef<AbortController | null>(null);
  const selectRequestSeqRef = useRef(0);
  const viewFilterRequestSeqRef = useRef(0);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedDetails, setSelectedDetails] = useState<NodeDetails | null>(null);
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
  const [previewContextError, setPreviewContextError] = useState("");
  const [error, setError] = useState("");
  const consumedCreateRequests = useRef<Set<string>>(new Set());
  const consumedPreviewRequests = useRef<Set<string>>(new Set());
  const consumedLegacyCreateRequest = useRef(false);
  const consumedLegacyPreviewRequest = useRef(false);
  const selectedIdRef = useRef<string | null>(null);

  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const selectedNode = selectedId ? nodeById.get(selectedId) || null : null;

  useEffect(() => {
    nodesRef.current = nodes;
  }, [nodes]);

  const hydrateGraph = useCallback((payload: { nodes?: GraphNode[]; edges?: GraphEdge[] }) => {
    const center = { x: 450, y: 310 };
    setNodes((current) => {
      const existing = new Map(current.map((node) => [node.id, node]));
      const incoming = payload.nodes || [];
      return incoming.map((node, index) => {
        const previous = existing.get(node.id);
        const angle = (index / Math.max(1, incoming.length)) * Math.PI * 2;
        const radius = 110 + Math.min(280, incoming.length * 10);
        return {
          ...node,
          x: previous?.x ?? center.x + Math.cos(angle) * radius,
          y: previous?.y ?? center.y + Math.sin(angle) * radius,
          vx: previous?.vx ?? 0,
          vy: previous?.vy ?? 0,
          radius: 13 + Math.min(13, Number(node.importance || 0.5) * 15),
        };
      });
    });
    setEdges(payload.edges || []);
  }, []);

  const refreshGraph = useCallback(async (override: { query: string; viewFilter: ViewFilter }) => {
    setGraphLoading(true);
    const effectiveQuery = override.query;
    const effectiveViewFilter = override.viewFilter;
    const body: Record<string, unknown> = { action: "graph", query: effectiveQuery, limit: 220 };
    if (effectiveViewFilter.mode === "custom") {
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

  const selectNode = useCallback(async (id: string | null) => {
    selectAbortRef.current?.abort();
    setSelectedId(id);
    selectedIdRef.current = id;
    if (!id) {
      setSelectedDetails(null);
      return;
    }
    notifyActiveMemorySelection(id, { ownerAppId: appId });
    const controller = new AbortController();
    selectAbortRef.current = controller;
    const requestId = selectRequestSeqRef.current + 1;
    selectRequestSeqRef.current = requestId;
    try {
      const payload = await callMemory<{ node: NodeDetails }>({ action: "inspect", node_id: id }, { signal: controller.signal });
      if (controller.signal.aborted || requestId !== selectRequestSeqRef.current || selectedIdRef.current !== id) {
        return;
      }
      setSelectedDetails(payload.node);
      setError("");
    } catch (inspectError) {
      if (isCancelledRequest(inspectError)) {
        return;
      }
      if (requestId === selectRequestSeqRef.current) {
        setSelectedDetails(null);
        setError(inspectError instanceof Error ? inspectError.message : "Unable to inspect node.");
      }
    }
  }, [appId]);

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
    }, 250);
  }, [refreshMemory]);

  useEffect(() => {
    return () => {
      if (eventRefreshTimerRef.current !== null) window.clearTimeout(eventRefreshTimerRef.current);
      graphAbortRef.current?.abort();
      previewAbortRef.current?.abort();
      selectAbortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    window.parent?.postMessage({ type: "maverick.app.ready", app_id: appId }, window.location.origin);
  }, [appId]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") return;
      const payload = event.data as {
        app_id?: string;
        owner_app_id?: string;
        params?: Record<string, string | boolean | null>;
        resource?: string;
        type?: string;
      };
      if (payload.type === "maverick.app.navigate" && (!payload.app_id || payload.app_id === appId)) {
        void handleNavigationParams(payload.params || {});
        return;
      }
      if (payload.type === "maverick.app.data-changed" && payload.owner_app_id === appId) scheduleEventRefresh();
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [appId, scheduleEventRefresh]);

  useEffect(() => {
    if (!("WebSocket" in window)) return undefined;
    let closed = false;
    let retry = 0;
    let reconnectTimer: number | null = null;
    let socket: WebSocket | null = null;
    const connect = () => {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(`${protocol}//${window.location.host}/api/apps/events/ws`);
      socket.onopen = () => {
        retry = 0;
      };
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === "maverick.app.data-changed" && payload.owner_app_id === appId) scheduleEventRefresh();
        } catch {
          // Ignore malformed event frames.
        }
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        if (closed) return;
        const delay = Math.min(5000, 500 + retry * 750);
        retry += 1;
        reconnectTimer = window.setTimeout(connect, delay);
      };
    };
    connect();
    return () => {
      closed = true;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      if (eventRefreshTimerRef.current !== null) window.clearTimeout(eventRefreshTimerRef.current);
      socket?.close();
    };
  }, [appId, scheduleEventRefresh]);

  const relationships = useMemo(() => {
    if (!selectedId) return [];
    return edges
      .filter((edge) => edge.source === selectedId || edge.target === selectedId)
      .map((edge) => {
        const otherId = edge.source === selectedId ? edge.target : edge.source;
        return { ...edge, otherId, other: nodeById.get(otherId), direction: edge.source === selectedId ? "Outgoing" : "Incoming" };
      });
  }, [edges, nodeById, selectedId]);

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
      const payload = await callMemory<{ items?: PreviewContextItem[] }>({
        action: "context",
        query: contextQuery,
        limit: 5,
      }, { signal: controller.signal });
      if (controller.signal.aborted || requestId !== previewRequestSeqRef.current) {
        return;
      }
      setPreviewContextItems(payload.items || []);
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
      {error ? <div className="memory-error">{error}</div> : null}
      <GraphCanvas
        nodes={nodes}
        edges={edges}
        selectedId={selectedId}
        selectedNode={selectedNode}
        selectedDetails={selectedDetails}
        loading={graphLoading}
        relationships={relationships}
        onSelectNode={selectNode}
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
      />
    </main>
  );
}

function isCancelledRequest(error: unknown): boolean {
  return error instanceof MemoryApiError && error.code === "request_cancelled";
}
