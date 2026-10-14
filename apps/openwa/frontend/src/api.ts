export interface Connection {
  url: string;
  configured: boolean;
  credential_available?: boolean;
  role?: string;
  engine?: string;
  scoped?: boolean;
}
export interface Session {
  id: string;
  name: string;
  status: string;
  phone?: string;
  pushName?: string;
  lastError?: string;
  engineLoaded?: boolean;
}
export interface Chat {
  id: string;
  name?: string;
  unreadCount?: number;
  isGroup?: boolean;
  lastMessage?: string;
}
export interface Message {
  id: string;
  waMessageId?: string;
  body?: string;
  type?: string;
  direction?: string;
  status?: string;
  timestamp?: number;
  createdAt?: string;
  chatName?: string;
}
export interface Status {
  send_scope: string;
  connection: Connection;
  can_configure: boolean;
  source: { repository: string; version: string };
}
export type Row = Record<string, unknown>;
export class BackendError extends Error {
  constructor(message: string, public status: number, public code: string) {
    super(message);
  }
}
export function items<T>(raw: unknown): T[] {
  if (Array.isArray(raw)) return raw as T[];
  if (raw && typeof raw === "object") {
    for (const key of [
      "items",
      "data",
      "sessions",
      "chats",
      "messages",
      "contacts",
      "webhooks",
      "templates",
    ]) {
      const value = (raw as Row)[key];
      if (Array.isArray(value)) return value as T[];
    }
  }
  return [];
}
export async function callBackend<T>(
  body: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) abort();
  signal?.addEventListener("abort", abort, { once: true });
  const timeout = setTimeout(abort, 28000);
  try {
    const response = await fetch("/api/apps/openwa/backend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => null);
      throw new BackendError(
        typeof error?.detail === "string" ? error.detail : `Request failed (${response.status}).`,
        response.status,
        typeof error?.error === "string" ? error.error : "request_failed",
      );
    }
    try {
      return await response.json() as T;
    } catch {
      throw new BackendError("Loopino returned an invalid response. Try refreshing.", 502, "invalid_response");
    }
  } catch (error) {
    if (controller.signal.aborted && !signal?.aborted) {
      const send = body.action === "messages.send" || body.action === "messages.reply";
      throw new BackendError(send
        ? "The request timed out. The message may already have been sent. Check the conversation before retrying."
        : "The request timed out. Try again.", 504, "request_timeout");
    }
    if (error instanceof TypeError)
      throw new BackendError("Could not reach Loopino. Check your connection and try again.", 503, "network_error");
    throw error;
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", abort);
  }
}
export async function operation<T>(action: string, args: Row = {}, signal?: AbortSignal): Promise<T> {
  const result = await callBackend<{ data: T }>({ action, ...args }, signal);
  return result.data;
}
