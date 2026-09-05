export type LocalMessage = { id: string; role: "user" | "assistant"; text: string };
export type LocalSnapshot = {
  available: boolean; configured?: boolean; phase?: string; notice?: string;
  messages?: LocalMessage[]; model?: string; transport?: string;
};

export function parseLocalSnapshot(value: unknown): LocalSnapshot {
  if (!value || typeof value !== "object") throw new Error("Risposta locale non valida.");
  const raw = value as Record<string, unknown>;
  if (raw.available === false) return { available: false };
  if (raw.available !== true || raw.transport !== "mac-direct" || !Array.isArray(raw.messages)
      || raw.messages.length > 200 || !["idle", "starting", "running", "ready"].includes(String(raw.phase))) {
    throw new Error("Risposta locale non valida.");
  }
  const messages = raw.messages.map((item): LocalMessage => {
    if (!item || typeof item.id !== "string" || item.id.length > 100
        || !["user", "assistant"].includes(item.role) || typeof item.text !== "string" || item.text.length > 64000) {
      throw new Error("Messaggio locale non valido.");
    }
    return { id: item.id, role: item.role, text: item.text };
  });
  return { available: true, configured: raw.configured === true, phase: String(raw.phase),
    notice: typeof raw.notice === "string" ? raw.notice.slice(0, 1000) : "",
    model: typeof raw.model === "string" ? raw.model.slice(0, 100) : "", transport: "mac-direct", messages };
}

export function requestLocalRuntime(action: "status" | "start" | "poll" | "stop", text?: string): Promise<LocalSnapshot> {
  const origin = (window as unknown as { __MAVERICK_PLATFORM_ORIGIN__?: string }).__MAVERICK_PLATFORM_ORIGIN__;
  if (!origin || window.parent === window) return Promise.resolve({ available: false });
  return new Promise((resolve, reject) => {
    const channel = new MessageChannel();
    const close = () => { clearTimeout(timer); channel.port1.close(); channel.port2.close(); };
    const timer = setTimeout(() => { close(); reject(new Error("Connessione locale non disponibile. Nessun reinvio automatico.")); }, action === "start" ? 180000 : 5000);
    channel.port1.onmessage = (event) => {
      close();
      if (event.data?.ok !== true) { reject(new Error("Richiesta locale negata. Controlla Configura Mac.")); return; }
      try { resolve(parseLocalSnapshot(event.data.result)); } catch (error) { reject(error); }
    };
    window.parent.postMessage({ type: "maverick.local-runtime.request.v1", action, ...(text === undefined ? {} : { text }) }, origin, [channel.port2]);
  });
}
