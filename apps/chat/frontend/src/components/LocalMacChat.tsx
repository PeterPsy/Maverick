import { useEffect, useRef, useState } from "react";
import { requestLocalRuntime, type LocalSnapshot } from "../lib/localRuntime";
import "../styles/localMacChat.css";

export function LocalMacChat() {
  const [snapshot, setSnapshot] = useState<LocalSnapshot>({ available: true });
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try { const result = await requestLocalRuntime("poll"); if (live.current) setSnapshot(result); }
      catch { if (live.current) setError("Collegamento locale interrotto. Non verrà usato il runtime Ubuntu."); }
      if (live.current) timer = setTimeout(poll, 750);
    };
    void poll();
    return () => { live.current = false; clearTimeout(timer); void requestLocalRuntime("stop").catch(() => undefined); };
  }, []);
  async function send() {
    if (sending || !text.trim()) return;
    setSending(true); setError("");
    const prompt = text;
    setText("");
    try { const result = await requestLocalRuntime("start", prompt); if (live.current) setSnapshot(result); }
    catch (failure) { if (live.current) setError(failure instanceof Error ? failure.message : "Turno non avviato."); }
    finally { if (live.current) setSending(false); }
  }
  const running = sending || snapshot.phase === "running" || snapshot.phase === "starting";
  return <section className="chatapp-local-mac" aria-label="Chat su questo Mac">
    <header><strong>Su questo Mac · Astra</strong><p>Conversazione locale separata. Screenshot diretti a OpenAI, non caricati su Ubuntu. Cronologia non sincronizzata.</p></header>
    <div className="chatapp-local-mac__messages" aria-live="polite">
      {snapshot.messages?.map((message) => <article key={message.id} data-role={message.role}>
        <strong>{message.role === "user" ? "Tu" : "Maverick"}</strong><div>{message.text || "…"}</div>
      </article>)}
    </div>
    <p role="status">{snapshot.notice || "Apri Configura Mac per autorizzare Codex e scegliere un'app."}</p>
    {error ? <p role="alert">{error}</p> : null}
    <form onSubmit={(event) => { event.preventDefault(); void send(); }}>
      <textarea aria-label="Messaggio al Codex locale" value={text} maxLength={12000}
        onChange={(event) => setText(event.target.value)} placeholder="Chiedi a Maverick di osservare l'app autorizzata…" />
      <button type="submit" disabled={running || !snapshot.configured || !text.trim()}>Invia sul Mac</button>
      <button type="button" onClick={() => { void requestLocalRuntime("stop").then(setSnapshot).catch(() => setError("Usa Interrompi tutto nella barra nativa.")); }}>Interrompi</button>
    </form>
  </section>;
}
