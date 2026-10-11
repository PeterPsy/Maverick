import type { GoogleService } from "../api";

type Post = <T>(path: string, body: unknown, signal?: AbortSignal) => Promise<T>;
type NativeOpener = { postMessage(body: { url: string }): Promise<unknown> };
export class GoogleAuthError extends Error {
  constructor(readonly code: string) { super(code); }
}

export function googleAuthorizationTarget(value: string): string {
  const url = new URL(value);
  if (url.origin !== "https://accounts.google.com" || url.pathname !== "/o/oauth2/v2/auth" || url.username || url.password) {
    throw new GoogleAuthError("google_flow_invalid");
  }
  return url.href;
}

function pause(signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => { clearTimeout(timer); signal?.removeEventListener("abort", abort); reject(new DOMException("Aborted", "AbortError")); };
    const timer = setTimeout(() => { signal?.removeEventListener("abort", abort); resolve(); }, 1200);
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
  });
}

export async function runGoogleFlow(mode: "login" | "connect", services: GoogleService[], post: Post,
  signal?: AbortSignal): Promise<"redirecting" | "completed"> {
  const handlers = (window as unknown as { webkit?: { messageHandlers?: {
    maverickExternalURL?: NativeOpener; sensesHost?: unknown; maverickDeviceUse?: unknown;
  } } }).webkit?.messageHandlers;
  const opener = handlers?.maverickExternalURL;
  if (!opener && (handlers?.sensesHost || handlers?.maverickDeviceUse)) throw new GoogleAuthError("google_native_update_required");
  const result = await post<{ authorization_url?: string; browser_url?: string; flow_id?: string }>(
    "/api/auth/google/start", { mode, services, transport: opener ? "system-browser" : "browser" }, signal);
  if (!opener) {
    window.location.assign(googleAuthorizationTarget(result.authorization_url ?? ""));
    return "redirecting";
  }
  const target = new URL(result.browser_url ?? "");
  if (target.origin !== window.location.origin || target.pathname !== "/" || target.search !== "?google_handoff=1"
      || !target.hash || target.username || target.password || !/^[a-f0-9]{64}$/.test(result.flow_id ?? "")) {
    throw new GoogleAuthError("google_flow_invalid");
  }
  const body = { flow_id: result.flow_id };
  let completed = false;
  try {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    if (await opener.postMessage({ url: target.href }) !== true) throw new GoogleAuthError("google_browser_unavailable");
    const deadline = Date.now() + 600_000;
    while (Date.now() < deadline) {
      await pause(signal);
      let receipt: { status: string; error?: string };
      try { receipt = await post("/api/auth/google/result", body, signal); }
      catch (error) {
        const status = (error as { status?: number }).status;
        if (signal?.aborted || (status !== undefined && status < 500)) throw error;
        continue;
      }
      if (receipt.status === "pending") continue;
      completed = true;
      if (receipt.status !== "completed") throw new GoogleAuthError(receipt.error ?? "google_flow_invalid");
      return "completed";
    }
    throw new GoogleAuthError("google_flow_expired");
  } finally {
    if (!completed) void post("/api/auth/google/cancel", body).catch(() => {});
  }
}
