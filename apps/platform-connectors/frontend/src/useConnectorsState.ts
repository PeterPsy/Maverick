import { isExactMaverickParentMessage } from "@maverick/pwa-cache";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  active,
  callBackend,
  type Collection,
  type Run,
  type State,
} from "./api";
import { ownerAppId, postToShell, sourceFromParams, tabFromParams } from "./sourceNavigation";
const empty: State = {
  sources: [],
  connections: [],
  runs: [],
  collections: [],
  media_runtime_available: false,
};

export function useConnectorsState() {
  const [state, setState] = useState<State>(empty);
  const [sourceId, setSourceId] = useState("instagram");
  const [tab, setTab] = useState<"explore" | "collections" | "history">(
    "explore",
  );
  const [selected, setSelected] = useState<Run | null>(null);
  const [collection, setCollection] = useState<Collection | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const polling = useRef(false);
  const filterDirty = useRef(false);
  const source = state.sources.find((s) => s.id === sourceId);
  const refresh = useCallback(async () => {
    const next = await callBackend<State>({ action: "status" });
    setState(next);
    setSourceId((current) => next.sources.some((item) => item.id === current) ? current : "instagram");
    if (!filterDirty.current) setFilter(next.view_state?.query || "");
    setSelected((current) =>
      current
        ? next.runs.find((run) => run.id === current.id) || current
        : null,
    );
    setLoading(false);
    return next;
  }, []);
  const perform = useCallback(
    async <T>(body: Record<string, unknown>): Promise<T | undefined> => {
      setBusy(true);
      setError("");
      try {
        const result = await callBackend<T>(body);
        await refresh();
        return result;
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [refresh],
  );
  useEffect(() => {
    if (!filterDirty.current) return;
    const timer = setTimeout(() => {
      void callBackend({ action: "set_view_filter", query: filter })
        .then(() => {
          filterDirty.current = false;
        })
        .catch((e) => setError(e.message));
    }, 500);
    return () => clearTimeout(timer);
  }, [filter]);

  useEffect(() => {
    let disposed = false;
    const init = async () => {
      try {
        await callBackend({ action: "connections.refresh" });
        if (!disposed) await refresh();
      } catch (e) {
        if (!disposed) {
          setError((e as Error).message);
          setLoading(false);
        }
      }
    };
    void init();
    const timer = window.setInterval(async () => {
      if (polling.current || document.hidden) return;
      polling.current = true;
      try {
        const next = await callBackend<State>({ action: "status" });
        for (const run of next.runs.filter(active))
          await callBackend({ action: "run.refresh", id: run.id });
        if (!disposed) await refresh();
      } catch (e) {
        if (!disposed) setError((e as Error).message);
      } finally {
        polling.current = false;
      }
    }, 3000);
    return () => {
      disposed = true;
      clearInterval(timer);
    };
  }, [refresh]);
  useEffect(() => {
    postToShell({ type: "maverick.app.selection-changed", owner_app_id: ownerAppId, selection: { source: sourceId } });
  }, [sourceId]);
  useEffect(() => {
    const navigate = (event: MessageEvent) => {
      if (
        !isExactMaverickParentMessage(event) ||
        event.data?.type !== "maverick.app.navigate" ||
        event.data.app_id !== "platform-connectors"
      )
        return;
      const params = event.data.params || {};
      if (typeof params.collection_id === "string")
        void callBackend<{ collection: Collection }>({
          action: "collection.get",
          id: params.collection_id,
        })
          .then((data) => {
            setCollection(data.collection);
            setTab("collections");
          })
          .catch((e) => setError(e.message));
      if (typeof params.run_id === "string")
        void callBackend<{ run: Run }>({ action: "run.get", id: params.run_id })
          .then((data) => {
            setSelected(data.run);
            setTab("history");
          })
          .catch((e) => setError(e.message));
      const requestedSource = sourceFromParams(params);
      const requestedTab = tabFromParams(params);
      if (requestedSource) {
        setSourceId(requestedSource);
        setTab(requestedTab || "explore");
        if (!requestedTab) setSelected(null);
      } else if (requestedTab) {
        setTab(requestedTab);
      }
    };
    const params = Object.fromEntries(
      new URLSearchParams(window.location.search),
    );
    const requestedSource = sourceFromParams(params);
    if (requestedSource) setSourceId(requestedSource);
    const requestedTab = tabFromParams(params);
    if (requestedTab) setTab(requestedTab);
    if (params.collection_id)
      void callBackend<{ collection: Collection }>({
        action: "collection.get",
        id: params.collection_id,
      })
        .then((data) => {
          setCollection(data.collection);
          setTab("collections");
        })
        .catch((e) => setError(e.message));
    if (params.run_id)
      void callBackend<{ run: Run }>({ action: "run.get", id: params.run_id })
        .then((data) => {
          setSelected(data.run);
          setTab("history");
        })
        .catch((e) => setError(e.message));
    window.addEventListener("message", navigate);
    postToShell({ type: "maverick.app.ready", app_id: ownerAppId });
    return () => window.removeEventListener("message", navigate);
  }, []);

  return {
    state,
    sourceId,
    setSourceId,
    tab,
    setTab,
    selected,
    setSelected,
    collection,
    setCollection,
    error,
    setError,
    busy,
    loading,
    filter,
    setFilter,
    filterDirty,
    source,
    perform,
  };
}
