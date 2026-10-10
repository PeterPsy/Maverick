import { SourceIcon } from "./SourceIcon";
import { useEffect, useState } from "react";
import {
  shellHref,
  type Connection,
  type Perform,
  type Run,
  type Source,
} from "./api";
import { operationNames } from "./presentation";
type Props = {
  source: Source;
  connections: Connection[];
  busy: boolean;
  perform: Perform;
  onRun: (run: Run) => void;
};
export function Composer({ source, connections, busy, perform, onRun }: Props) {
  const sourceId = source.id;
  const [operation, setOperation] = useState(
    source.operations.includes("collect") ? "collect" : source.operations[0],
  );
  const [input, setInput] = useState("");
  const [session, setSession] = useState("");
  const [maxItems, setMaxItems] = useState(30);
  const [maxSeconds, setMaxSeconds] = useState(90);
  const [frameCount, setFrameCount] = useState(6);
  const [details, setDetails] = useState(true);
  const [reels, setReels] = useState(true);
  const [language, setLanguage] = useState("en");
  const [kind, setKind] = useState("");
  const sessions = connections.filter(
    (c) =>
      c.platform === sourceId &&
      c.status === "connected" &&
      (!c.expires_at || c.expires_at > Date.now() / 1000),
  );
  const needsChrome = source.backend === "chrome";
  useEffect(() => {
    if (session && !sessions.some((c) => c.session_id === session))
      setSession("");
    else if (!session && needsChrome) setSession(sessions[0]?.session_id || "");
  }, [connections, sourceId, session, needsChrome]);
  const start = async () => {
    const parameters: Record<string, unknown> = {
      max_items: maxItems,
      max_batches: 12,
      max_details: maxItems,
      read_details: details,
      include_reels: reels,
      max_seconds: maxSeconds,
      frame_count: frameCount,
      include_audio: true,
      language,
    };
    if (sourceId === "github" && ["search", "collect"].includes(operation))
      parameters.kind =
        kind || (operation === "search" ? "repositories" : "issues");
    if (needsChrome || (sourceId === "youtube" && session))
      parameters.session_id = session;
    if (operation === "search") parameters.query = input;
    else if (input.trim())
      parameters[/^https?:\/\//i.test(input) ? "url" : "username"] =
        input.trim();
    const result = await perform<{ run: Run }>({
      action: "run.start",
      source: sourceId,
      operation,
      parameters,
    });
    if (result) onRun(result.run);
  };
  return (
    <section className="composer">
      <div className="source-heading">
        <span className={"source-symbol large " + sourceId}>
          <SourceIcon source={sourceId} />
        </span>
        <div>
          <h2>{source.name}</h2>
          <p>{source.description}</p>
        </div>
        <span className={"tag " + (!needsChrome || session ? "observed" : "")}>
          {needsChrome
            ? session
              ? "Tab shared"
              : "Share a tab"
            : "Public source"}
        </span>
      </div>
      {(needsChrome || sourceId === "youtube") && (
        <div className="connection-row">
          <label htmlFor="sharing">
            {sourceId === "youtube"
              ? "Optional shared tab (public access fallback)"
              : "Shared Chrome tab"}
          </label>
          <select
            id="sharing"
            value={session}
            onChange={(e) => setSession(e.target.value)}
          >
            <option value="">
              {sourceId === "youtube"
                ? "Public reader (no shared tab)"
                : `Choose a shared ${source.name} tab`}
            </option>
            {sessions.map((c) => (
              <option key={c.session_id} value={c.session_id}>
                {c.display_name} · {c.url}
              </option>
            ))}
          </select>
          <button
            onClick={() => void perform({ action: "connections.refresh" })}
            disabled={busy}
          >
            Refresh
          </button>
        </div>
      )}
      {needsChrome && !session && (
        <p className="connection-help">
          Open Browser, connect Chrome Companion, then share a {source.name} tab
          from the extension. Keep the connector window open.{" "}
          <a href={shellHref("/app/browser")} target="_top">
            Open Browser ↗
          </a>
        </p>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void start();
        }}
      >
        <div className="input-row">
          <label className="field">
            <span>Action</span>
            <select
              value={operation}
              onChange={(e) => {setOperation(e.target.value);setKind("");}}
            >
              {source.operations.map((op) => (
                <option value={op} key={op}>
                  {operationNames[op]}
                </option>
              ))}
            </select>
          </label>
          <label className="field query-field">
            <span>
              {operation === "search"
                ? "Search query"
                : operation === "profile"
                  ? "Username or profile URL"
                  : "Source URL" + (needsChrome ? " or username" : "")}
            </span>
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={
                operation === "search"
                  ? `Search ${source.name}…`
                  : sourceId === "instagram"
                    ? "@username or https://www.instagram.com/username/"
                    : source.home || "https://example.com/feed.xml"
              }
              maxLength={operation === "search" ? 500 : 2048}
            />
          </label>
          <button
            className="primary launch"
            type="submit"
            disabled={busy || (needsChrome && !session)}
          >
            {busy ? "Working…" : operationNames[operation]}{" "}
            <span aria-hidden>→</span>
          </button>
        </div>
        <details className="options">
          <summary>Reading options</summary>
          <div className="options-grid">
            {sourceId === "github" &&
              ["search", "collect"].includes(operation) && (
                <label className="field">
                  <span>Content type</span>
                  <select
                    aria-label="Content type"
                    value={
                      kind ||
                      (operation === "search" ? "repositories" : "issues")
                    }
                    onChange={(e) => setKind(e.target.value)}
                  >
                    {(operation === "search"
                      ? ["repositories", "issues", "users"]
                      : ["issues", "pulls", "releases", "commits"]
                    ).map((value) => (
                      <option key={value}>{value}</option>
                    ))}
                  </select>
                </label>
              )}
            <label className="field">
              <span>Item limit</span>
              <input
                type="number"
                min="1"
                max="200"
                value={maxItems}
                onChange={(e) => setMaxItems(Number(e.target.value))}
              />
            </label>
            {["video", "transcript"].includes(operation) && (
              <>
                <label className="field">
                  <span>Video frames</span>
                  <input
                    type="number"
                    min="1"
                    max="12"
                    value={frameCount}
                    onChange={(e) => setFrameCount(Number(e.target.value))}
                  />
                </label>
                <label className="field">
                  <span>Audio limit (seconds)</span>
                  <input
                    type="number"
                    min="1"
                    max="180"
                    value={maxSeconds}
                    onChange={(e) => setMaxSeconds(Number(e.target.value))}
                  />
                </label>
                <label className="field">
                  <span>Preferred language</span>
                  <input
                    value={language}
                    maxLength={20}
                    onChange={(e) => setLanguage(e.target.value)}
                  />
                </label>
              </>
            )}
            {["collect", "search"].includes(operation) && needsChrome && (
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={details}
                  onChange={(e) => setDetails(e.target.checked)}
                />
                Open each result to read its content
              </label>
            )}
            {sourceId === "instagram" && operation === "collect" && (
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={reels}
                  onChange={(e) => setReels(e.target.checked)}
                />
                Include Reels
              </label>
            )}
          </div>
        </details>
      </form>
    </section>
  );
}
