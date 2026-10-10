import {
  reportShellAuthorizationFailure,
  shellAuthorizationEpoch,
} from "./shellAuthorization";
import type { AppLogo } from "./api";

export type Notice = {
  id: string;
  title: string;
  body?: string;
  created_at?: string;
  read?: boolean;
  presentation?: Record<string, unknown>;
  actions?: { id: string; label: string; done?: string }[];
  action_done?: string;
  scheduled_at?: string;
  timezone?: string;
  open_params?: Record<string, string | boolean | null>;
};
export type Inbox = {
  appId: string;
  name: string;
  logo: AppLogo | null;
  notices: Notice[];
  total: number;
  unread: number;
  capabilities: { read: boolean; actions: boolean };
};

export function noticeKey(appId: string, id: string | null) {
  return JSON.stringify([appId, id]);
}

export function validNotice(value: unknown): value is Notice {
  return Boolean(
    value &&
    typeof value === "object" &&
    typeof (value as Notice).id === "string" &&
    (value as Notice).id &&
    typeof (value as Notice).title === "string",
  );
}

export function noticeTime(notice: Notice) {
  if (typeof notice.scheduled_at !== "string") return undefined;
  try {
    return new Date(notice.scheduled_at!).toLocaleString(undefined, {
      dateStyle: "short",
      timeStyle: "short",
      timeZone: typeof notice.timezone === "string" ? notice.timezone : "UTC",
    });
  } catch {
    return notice.scheduled_at;
  }
}

export async function request(
  appId: string,
  body: object,
  signal?: AbortSignal,
) {
  const epoch = shellAuthorizationEpoch();
  const response = await fetch(
    `/api/apps/${encodeURIComponent(appId)}/backend`,
    {
      method: "POST",
      credentials: "same-origin",
      signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...body,
        _app_secret_request: { required: false, logical_names: [] },
      }),
    },
  );
  if (signal?.aborted) throw new DOMException("Request aborted.", "AbortError");
  if (!response.ok) {
    if (response.status === 401 && epoch === shellAuthorizationEpoch())
      void reportShellAuthorizationFailure(response.status);
    throw new Error(`Richiesta notifiche fallita (${response.status}).`);
  }
  const value = await response.json();
  if (value.error) throw new Error(value.detail || value.error);
  return value;
}
