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
): Promise<T> {
  const response = await fetch("/api/apps/openwa/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new BackendError(
      error.detail || error.error || `Request failed (${response.status}).`,
      response.status,
      error.error || "request_failed",
    );
  }
  return response.json() as Promise<T>;
}
export async function operation<T>(action: string, args: Row = {}): Promise<T> {
  const result = await callBackend<{ data: T }>({ action, ...args });
  return result.data;
}
