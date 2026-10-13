import { useEffect, useRef, useState } from "react";
import { operation } from "./api";

export function MessageImage({ sessionId, chatId, messageId, available }: {
  sessionId: string; chatId: string; messageId: string; available: boolean;
}) {
  const [src, setSrc] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => { request.current?.abort(); }, []);

  async function load() {
    if (request.current && !request.current.signal.aborted) return;
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    setError("");
    try {
      const image = await operation<{ mimetype: string; content_base64: string }>("messages.image", {
        session_id: sessionId, chat_id: chatId, message_id: messageId,
      }, controller.signal);
      if (!controller.signal.aborted) setSrc(`data:${image.mimetype};base64,${image.content_base64}`);
    } catch (error) {
      if (!controller.signal.aborted) setError((error as Error).message);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
      if (request.current === controller) request.current = null;
    }
  }
  return <div className="message-image">
    {src ? <img src={src} alt="WhatsApp image" /> : <button type="button" onClick={load} disabled={loading || !available}>
      {loading ? "Loading image…" : error ? "Retry image" : "View image"}
    </button>}
    {error && <p role="alert">{error}</p>}
  </div>;
}
