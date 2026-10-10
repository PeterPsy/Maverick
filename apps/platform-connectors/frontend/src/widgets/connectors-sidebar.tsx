import { isExactMaverickParentMessage } from "@maverick/pwa-cache";
import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { callBackend, type Source } from "../api";
import { SourceIcon } from "../SourceIcon";
import { ownerAppId, sidebarWidgetId, sidebarContext, sourceSelection, postToShell } from "../sourceNavigation";
import "../tokens.css";
import "./connectors-sidebar.css";

function ConnectorsSidebar() {
  const [sources, setSources] = useState<Source[]>([]);
  const [selected, setSelected] = useState("instagram");
  const [workspace, setWorkspace] = useState("");
  const [isMobile, setIsMobile] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setSources([]);
    setError("");
    void callBackend<{ sources: Source[] }>({ action: "sources.list" }, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setSources(data.sources);
      })
      .catch((cause: Error) => {
        if (!controller.signal.aborted) setError(cause.message || "Unable to load sources.");
      });
    return () => controller.abort();
  }, [workspace, retry]);

  useEffect(() => {
    function receive(event: MessageEvent) {
      if (!isExactMaverickParentMessage(event) || !event.data || typeof event.data !== "object") return;
      const context = sidebarContext(event.data);
      if (context) {
        setWorkspace(context.workspaceId);
        setSelected(context.source);
        setIsMobile(context.isMobile);
        return;
      }
      const source = sourceSelection(event.data);
      if (source) setSelected(source);
    }
    window.addEventListener("message", receive);
    postToShell({ type: "maverick.widget.ready", owner_app_id: ownerAppId, widget_id: sidebarWidgetId });
    return () => window.removeEventListener("message", receive);
  }, []);

  function choose(source: string) {
    setSelected(source);
    postToShell({ type: "maverick.widget.open-app", app_id: ownerAppId, params: { source } });
    if (isMobile) postToShell({ type: "maverick.shell.sidebar.close" });
  }

  return (
    <main className={`connectors-sidebar ${isMobile ? "is-shell-mobile" : ""}`}>
      <div className="connectors-sidebar-scroll">
        <header className="sources-label">Sources <span>{sources.length || ""}</span></header>
        {error ? <div className="sources-error" role="alert"><p>{error}</p><button onClick={() => setRetry((value) => value + 1)}>Retry</button></div> : null}
        {!error && !sources.length ? <p className="sources-loading" role="status">Loading sources…</p> : null}
        <nav aria-label="Sources">
          {sources.map((source) => (
            <button key={source.id} className={`source-option ${selected === source.id ? "selected" : ""}`}
              aria-pressed={selected === source.id} onClick={() => choose(source.id)} type="button">
              <span className="source-icon"><SourceIcon source={source.id} /></span>
              <span>{source.name}</span>
            </button>
          ))}
        </nav>
        <p className="sources-note">Your sign-in stays in Chrome. Observations and saved collections are private to your Maverick user.</p>
      </div>
    </main>
  );
}

createRoot(document.getElementById("connectors-sidebar-root")!).render(<ConnectorsSidebar />);
