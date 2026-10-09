import {
  reportShellAuthorizationFailure,
  shellAuthorizationEpoch,
} from "./shellAuthorization";

export type Notice = {
  id: string;
  title: string;
  scheduled_at?: string;
  timezone?: string;
  open_params?: Record<string, string | boolean | null>;
};
export type Inbox = {
  appId: string;
  name: string;
  notices: Notice[];
  total: number;
};

export function noticeTime(notice: Notice) {
  try {
    return new Date(notice.scheduled_at!).toLocaleString(undefined, {
      dateStyle: "short",
      timeStyle: "short",
      timeZone: notice.timezone || "UTC",
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
