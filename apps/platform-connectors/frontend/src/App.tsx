import { useEffect, useRef } from "react";
import { SourceIcon } from "./SourceIcon";
import { Composer } from "./Composer";
import { CollectionPanel } from "./CollectionPanel";
import { RunPanel } from "./RunPanel";
import { Results } from "./Results";
import { operationNames } from "./presentation";
import { shellHref, dateLabel, type Collection } from "./api";
import { useConnectorsState } from "./useConnectorsState";
export function App() {
  const mainPanel = useRef<HTMLElement>(null);
  const {
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
  } = useConnectorsState();
  useEffect(() => {
    mainPanel.current?.scrollTo({ top: 0 });
  }, [tab]);
  const chooseSource = (id: string) => {
    setSourceId(id);
    setTab("explore");
    setSelected(null);
  };
  const openCollection = async (id: string) => {
    const result = await perform<{ collection: Collection }>({
      action: "collection.get",
      id,
    });
    if (result) {
      setCollection(result.collection);
    }
  };
  const items =
    tab === "collections" ? collection?.items : selected?.result.items;
  const filteredCollections = state.collections.filter(
    (c) =>
      `${c.title} ${c.source}`.toLowerCase().includes(filter.toLowerCase()) &&
      (!state.view_state?.source || c.source === state.view_state.source) &&
      (state.view_state?.mode !== "custom" ||
        state.view_state.ids.includes(c.id)),
  );

  return (
    <div className="connectors-app">
      <header className="app-header">
        <div className="brand">
          <img
            src="/apps/platform-connectors/maverick-icon-compact.png"
            alt=""
          />
          <div>
            <h1>Connectors</h1>
            <p>Read, research and keep the sources that matter.</p>
          </div>
        </div>
        <a
          className="button secondary"
          href={shellHref("/app/browser")}
          target="_top"
        >
          Manage connections ↗
        </a>
      </header>
      <div className="workspace-grid">
        <aside className="sources">
          <div className="section-label">
            Sources <span>{state.sources.length}</span>
          </div>
          <nav aria-label="Sources">
            {state.sources.map((s) => (
              <button
                key={s.id}
                className={
                  "source-option " + (s.id === sourceId ? "selected" : "")
                }
                aria-pressed={s.id === sourceId}
                onClick={() => chooseSource(s.id)}
              >
                <span className={"source-symbol " + s.id}>
                  <SourceIcon source={s.id} />
                </span>
                <span>{s.name}</span>
              </button>
            ))}
          </nav>
          <p className="aside-note">
            Your sign-in stays in Chrome. Observations and saved collections are
            private to your Maverick user.
          </p>
        </aside>
        <main ref={mainPanel} className="main-panel">
          <nav className="tabs" aria-label="Workspace">
            <button
              aria-current={tab === "explore" ? "page" : undefined}
              onClick={() => setTab("explore")}
            >
              Explore
            </button>
            <button
              aria-current={tab === "collections" ? "page" : undefined}
              onClick={() => setTab("collections")}
            >
              Collections <span>{state.collections.length}</span>
            </button>
            <button
              aria-current={tab === "history" ? "page" : undefined}
              onClick={() => setTab("history")}
            >
              History
            </button>
          </nav>
          {error && (
            <div role="alert" className="notice error">
              <span>{error}</span>
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                ×
              </button>
            </div>
          )}
          {loading && (
            <div className="empty-state" role="status">
              Loading your connectors…
            </div>
          )}
          {tab === "explore" && source && (
            <Composer
              key={source.id}
              source={source}
              connections={state.connections}
              busy={busy}
              perform={perform}
              onRun={setSelected}
            />
          )}
          {tab === "history" && (
            <section className="history-list">
              <h2>Observation history</h2>
              {!state.runs.length && (
                <p>
                  No observations yet. Start with Instagram or a public source.
                </p>
              )}
              {state.runs.map((run) => (
                <button
                  key={run.id}
                  className={
                    "history-row " + (selected?.id === run.id ? "selected" : "")
                  }
                  onClick={() => setSelected(run)}
                >
                  <span className={"source-symbol " + run.source}>
                    <SourceIcon source={run.source} />
                  </span>
                  <span>
                    <strong>
                      {state.sources.find((s) => s.id === run.source)?.name} ·{" "}
                      {operationNames[run.operation] || run.operation}
                    </strong>
                    <small>{dateLabel(run.created_at)}</small>
                  </span>
                  <span className={"tag " + run.status}>{run.status}</span>
                </button>
              ))}
            </section>
          )}
          {tab === "collections" && (
            <section className="collection-board">
              <div className="board-header">
                <h2>{state.view_state?.title || "Saved collections"}</h2>
                {state.view_state?.mode === "custom" && (
                  <button
                    onClick={() =>
                      void perform({ action: "clear_custom_view" })
                    }
                  >
                    Show all
                  </button>
                )}
                <input
                  aria-label="Search collections"
                  placeholder="Search collections…"
                  value={filter}
                  onChange={(e) => {
                    filterDirty.current = true;
                    setFilter(e.target.value);
                  }}
                />
              </div>
              <div className="collection-grid">
                {filteredCollections.map((c) => (
                  <button
                    className={
                      "collection-card " +
                      (collection?.id === c.id ? "selected" : "")
                    }
                    key={c.id}
                    onClick={() => void openCollection(c.id)}
                  >
                    <span className="meta">
                      {state.sources.find((s) => s.id === c.source)?.name}
                    </span>
                    <strong>{c.title}</strong>
                    <span>
                      {c.total} saved items · {dateLabel(c.updated_at)}
                    </span>
                  </button>
                ))}
              </div>
              {!filteredCollections.length && (
                <div className="empty-state">
                  <h3>Keep a useful source</h3>
                  <p>
                    Complete an observation, then save its results as a
                    collection. Refresh it later to merge new items.
                  </p>
                </div>
              )}
            </section>
          )}
          {tab !== "collections" && selected && (
            <RunPanel
              key={selected.id}
              selected={selected}
              state={state}
              busy={busy}
              perform={perform}
              onRun={setSelected}
              onCollection={(value) => {
                setCollection(value);
                setTab("collections");
              }}
            />
          )}
          {tab === "collections" && collection && (
            <CollectionPanel
              key={collection.id}
              collection={collection}
              connections={state.connections}
              busy={busy}
              perform={perform}
              onCollection={setCollection}
              onRun={(run) => {
                setSelected(run);
                setTab("history");
              }}
            />
          )}
          {tab !== "collections" &&
            !!selected?.result.context_items?.length && (
              <section className="source-context">
                <h2 className="context-label">Profile and source pages</h2>
                <Results items={selected.result.context_items} />
              </section>
            )}
          {items && <Results items={items} />}
          {tab === "collections" && collection?.has_more && (
            <button
              className="load-more"
              disabled={busy}
              onClick={async () => {
                const next = await perform<{ collection: Collection }>({
                  action: "collection.get",
                  id: collection.id,
                  offset: collection.next_offset,
                });
                if (next)
                  setCollection({
                    ...next.collection,
                    items: [...collection.items, ...next.collection.items],
                  });
              }}
            >
              Load more saved items
            </button>
          )}
          {tab === "explore" && !selected && !loading && (
            <div className="empty-state">
              <div className="empty-symbol"><SourceIcon source="instagram" /></div>
              <h3>Your sources, in one place</h3>
              <p>
                Start with an Instagram profile, inspect a Reel, or read a
                public source. Save observations with their original links and
                coverage.
              </p>
              <div className="quick-sources">
                <button onClick={() => chooseSource("youtube")}>
                  YouTube transcripts →
                </button>
                <button onClick={() => chooseSource("rss")}>
                  Read a feed →
                </button>
                <button onClick={() => chooseSource("github")}>
                  Explore GitHub →
                </button>
              </div>
            </div>
          )}
          <footer>
            Sources are observed at a point in time. Sign-in walls, unloaded
            content and source limits are reported in each result.
          </footer>
        </main>
      </div>
    </div>
  );
}
