import { useEffect, useRef, useState } from "react";
import { requestJson } from "../api/client";

type EvidencePage = { content: string; has_more: boolean; next_offset: number | null; has_image: boolean };

export function DeviceUseAuditPanel({ turnId, callId }: { turnId: string; callId: string }) {
  const [page, setPage] = useState<EvidencePage | null>(null);
  const [content, setContent] = useState("");
  const [image, setImage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const imageRef = useRef("");
  const path = `/api/runtime/turns/${encodeURIComponent(turnId)}/device-use-audit?call_id=${encodeURIComponent(callId)}`;

  useEffect(() => {
    setPage(null); setContent(""); setImage(""); setError(""); setBusy(false);
    return () => {
      controller.current?.abort();
      if (imageRef.current) URL.revokeObjectURL(imageRef.current);
      imageRef.current = "";
    };
  }, [path]);

  async function load(asImage = false) {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setBusy(true); setError("");
    try {
      if (asImage) {
        const response = await fetch(`${path}&image=true`, { credentials: "same-origin", signal: current.signal });
        if (!response.ok) throw new Error("Screenshot non disponibile.");
        const blob = await response.blob();
        if (current.signal.aborted) return;
        const url = URL.createObjectURL(blob);
        if (imageRef.current) URL.revokeObjectURL(imageRef.current);
        imageRef.current = url; setImage(url);
      } else {
        const result = await requestJson<EvidencePage>(`${path}&offset=${page?.next_offset ?? 0}`, { signal: current.signal });
        if (current.signal.aborted) return;
        setPage(result); setContent((previous) => previous + result.content);
      }
    } catch {
      if (!current.signal.aborted) setError("Evidenze non disponibili per questa chiamata. Le chiamate precedenti all’aggiornamento conservano solo il registro delle azioni.");
    } finally {
      if (!current.signal.aborted) setBusy(false);
    }
  }

  return <div>
    {!page || page.has_more ? <button type="button" className="chat-ui-button chat-ui-button--ghost" disabled={busy} onClick={() => void load()}>
      {busy ? "Caricamento…" : page ? "Leggi altro" : "Carica evidenze Mac"}
    </button> : null}
    {page?.has_image && !image ? <button type="button" className="chat-ui-button chat-ui-button--ghost" disabled={busy} onClick={() => void load(true)}>Mostra screenshot</button> : null}
    {error ? <p role="status">{error}</p> : null}
    {content ? <pre className="chatapp-tool-call-panel__pre">{content}</pre> : null}
    {image ? <img src={image} alt="Osservazione Mac associata alla chiamata" style={{ maxWidth: "100%" }} /> : null}
  </div>;
}
