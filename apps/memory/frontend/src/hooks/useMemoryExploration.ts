import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { notifyActiveMemorySelection } from "../lib/activeMemorySelection";
import { callMemory, MemoryApiError } from "../memoryApi";
import type { Subgraph } from "../lib/graphSubgraph";
import type { ExploreResult, GraphEdge, GraphNode, NodeDetails } from "../types";

type NavigationOptions = {
  appId: string;
  focusedGraphRef: RefObject<Subgraph | null>;
  nodesRef: RefObject<GraphNode[]>;
  edgesRef: RefObject<GraphEdge[]>;
  hydrateGraph: (graph: Subgraph) => void;
  setError: (error: string) => void;
};

export function useMemoryExploration({ appId, focusedGraphRef, nodesRef, edgesRef, hydrateGraph, setError }: NavigationOptions) {
  const selectAbortRef = useRef<AbortController | null>(null);
  const selectRequestSeqRef = useRef(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedDetails, setSelectedDetails] = useState<NodeDetails | null>(null);
  const selectedIdRef = useRef<string | null>(null);
  const [connectionCursor, setConnectionCursor] = useState<string | null>(null);
  const [connectionLoading, setConnectionLoading] = useState(false);
  const [connectionGraph, setConnectionGraph] = useState<Subgraph>({ nodes: [], edges: [] });
  const navigationHistory = useRef<string[]>([]);
  const [canGoBack, setCanGoBack] = useState(false);
  const selectNode = useCallback(async (id: string | null, back = false) => {
    selectAbortRef.current?.abort();
    if (!back && id && selectedIdRef.current && id !== selectedIdRef.current) navigationHistory.current.push(selectedIdRef.current);
    setCanGoBack(navigationHistory.current.length > 0);
    setSelectedDetails(null);
    setConnectionCursor(null);
    setConnectionGraph({ nodes: [], edges: [] });
    setConnectionLoading(false);
    setSelectedId(id);
    selectedIdRef.current = id;
    if (!id) {
      focusedGraphRef.current = null;
      return;
    }
    notifyActiveMemorySelection(id, { ownerAppId: appId });
    const controller = new AbortController();
    selectAbortRef.current = controller;
    const requestId = selectRequestSeqRef.current + 1;
    selectRequestSeqRef.current = requestId;
    try {
      const neighborhood = await callMemory<ExploreResult>({ action: "explore", node_ids: [id], limit: 8, max_bytes: 12000 }, { signal: controller.signal });
      let card = neighborhood.nodes.find((node) => node.id === id);
      if (!card) {
        const inspected = await callMemory<{ node: NodeDetails }>({ action: "inspect", node_id: id, detail: "card" }, { signal: controller.signal });
        card = inspected.node;
        neighborhood.nodes.unshift(card);
      }
      if (controller.signal.aborted || requestId !== selectRequestSeqRef.current || selectedIdRef.current !== id) {
        return;
      }
      setSelectedDetails(card);
      setConnectionGraph(neighborhood);
      setConnectionCursor(neighborhood.next_cursor);
      focusedGraphRef.current = neighborhood;
      hydrateGraph({ nodes: nodesRef.current, edges: edgesRef.current });
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
  }, [appId, hydrateGraph]);

  async function moreConnections() {
    const id = selectedIdRef.current;
    if (!id || !connectionCursor || connectionLoading) return;
    const controller = selectAbortRef.current;
    setConnectionLoading(true);
    try {
      const result = await callMemory<ExploreResult>({ action: "explore", node_ids: [id], limit: 8, cursor: connectionCursor, max_bytes: 12000 }, { signal: controller?.signal });
      if (controller?.signal.aborted || selectedIdRef.current !== id) return;
      setConnectionGraph((current) => ({ nodes: [...new Map([...current.nodes, ...result.nodes].map((node) => [node.id, node])).values()],
        edges: [...new Map([...current.edges, ...result.edges].map((edge) => [edge.id, edge])).values()] }));
      focusedGraphRef.current = result;
      hydrateGraph({ nodes: nodesRef.current, edges: edgesRef.current });
      setConnectionCursor(result.next_cursor);
    } catch (problem) { if (!isCancelledRequest(problem)) setError(problem instanceof Error ? problem.message : "Unable to explore connections."); }
    finally { setConnectionLoading(false); }
  }

  function goBack() {
    const previous = navigationHistory.current.pop();
    if (previous) void selectNode(previous, true);
  }

  const relationships = useMemo(() => {
    if (!selectedId) return [];
    const cards = new Map(connectionGraph.nodes.map((node) => [node.id, node]));
    return connectionGraph.edges.filter((edge) => edge.source === selectedId || edge.target === selectedId).map((edge) => {
      const otherId = edge.source === selectedId ? edge.target : edge.source;
      return { ...edge, otherId, other: cards.get(otherId), direction: edge.source === selectedId ? "Outgoing" : "Incoming" };
    });
  }, [connectionGraph, selectedId]);
  useEffect(() => () => selectAbortRef.current?.abort(), []);
  return { selectedId, selectedDetails, selectedIdRef, selectNode, moreConnections, goBack, canGoBack, relationships, connectionCursor, connectionLoading };
}

function isCancelledRequest(error: unknown): boolean {
  return error instanceof MemoryApiError && error.code === "request_cancelled";
}
