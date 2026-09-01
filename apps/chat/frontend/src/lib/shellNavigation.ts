type ShellPostTarget = {
  postMessage: (message: unknown, targetOrigin: string) => void;
};

type ShellRouteOptions = {
  currentWindow?: unknown;
  navigationScope?: string;
  origin?: string;
  parentWindow?: ShellPostTarget | null;
};
export type ShellRouteParams = Record<string, string | boolean | null>;

export type ShellAppHrefTarget = {
  appId: string;
  params: ShellRouteParams;
};

export type RuntimeSessionThreadMetadata = {
  agent_label?: string;
  agent_type_id?: string;
  agent_role_id?: string;
  source_app_id?: string;
  title?: string;
};

export function openChatThreadRouteInShell(threadId: string, options: ShellRouteOptions = {}): boolean {
  const normalizedThreadId = threadId.trim();
  if (!normalizedThreadId) {
    return false;
  }
  return postChatRouteToShell({ app_page: `threads/${normalizedThreadId}` }, options);
}

export function openChatRootRouteInShell(options: ShellRouteOptions = {}): boolean {
  return postChatRouteToShell({}, options);
}

export function openAppRouteInShell(appId: string, appPage: string, options: ShellRouteOptions = {}): boolean {
  const normalizedAppId = appId.trim();
  if (!normalizedAppId) {
    return false;
  }
  return postAppRouteToShell(normalizedAppId, { app_page: appPage.trim().replace(/^\/+/, "") }, options);
}

export function openAppParamsInShell(appId: string, params: ShellRouteParams = {}, options: ShellRouteOptions = {}): boolean {
  const normalizedAppId = appId.trim();
  if (!normalizedAppId) {
    return false;
  }
  return postAppRouteToShell(normalizedAppId, params, options);
}

/**
 * Open an app from either the full Chat app or a shell-owned Chat widget.
 * Scoped floating surfaces use the widget command because their navigation
 * scope belongs to Chat rather than to the destination app.
 */
export function openContextAppParamsInShell(
  appId: string,
  params: ShellRouteParams = {},
  options: ShellRouteOptions = {},
): boolean {
  const normalizedAppId = appId.trim();
  if (!normalizedAppId) {
    return false;
  }
  if (!options.navigationScope) {
    return postAppRouteToShell(normalizedAppId, params, options);
  }
  const currentWindow = options.currentWindow ?? (typeof window === "undefined" ? null : window);
  const parentWindow = options.parentWindow ?? (typeof window === "undefined" ? null : window.parent);
  if (!parentWindow || parentWindow === currentWindow) {
    return false;
  }
  const origin = options.origin ?? "*";
  parentWindow.postMessage(
    {
      type: "maverick.widget.open-app",
      app_id: normalizedAppId,
      params,
    },
    origin,
  );
  return true;
}

export function openStoragePathInShell(workspaceRelativePath: string, options: ShellRouteOptions = {}): boolean {
  const normalizedPath = workspaceRelativePath.trim();
  if (!normalizedPath) {
    return false;
  }
  return postAppRouteToShell("storage", { workspace_relative_path: normalizedPath }, options);
}

export function shellAppHrefTarget(value: unknown): ShellAppHrefTarget | null {
  if (typeof value !== "string" || !value.startsWith("/app/")) {
    return null;
  }
  let url: URL;
  try {
    url = new URL(value, "https://maverick.invalid");
  } catch {
    return null;
  }
  const segments = url.pathname
    .slice("/app/".length)
    .split("/")
    .filter(Boolean)
    .map(decodePathSegment);
  const [appId = "", ...pageSegments] = segments;
  if (!appId.trim()) {
    return null;
  }
  const params: ShellRouteParams = Object.fromEntries(url.searchParams.entries());
  if (pageSegments.length) {
    params.app_page = pageSegments.join("/");
  }
  return { appId, params };
}

function postChatRouteToShell(params: ShellRouteParams, options: ShellRouteOptions): boolean {
  return postAppRouteToShell("chat", params, options);
}

function postAppRouteToShell(appId: string, params: ShellRouteParams, options: ShellRouteOptions): boolean {
  if (options.navigationScope) {
    return false;
  }
  const currentWindow = options.currentWindow ?? (typeof window === "undefined" ? null : window);
  const parentWindow = options.parentWindow ?? (typeof window === "undefined" ? null : window.parent);
  if (!parentWindow || parentWindow === currentWindow) {
    return false;
  }
  const origin = options.origin ?? "*";
  parentWindow.postMessage(
    {
      type: "maverick.app.open-app",
      app_id: appId,
      params,
    },
    origin,
  );
  return true;
}

export function runtimeSessionThreadMetadataFromParams(params: ShellRouteParams): RuntimeSessionThreadMetadata {
  const agentLabel = scalarString(params.agent_label);
  const threadTitle = scalarString(params.thread_title) || agentLabel;
  return {
    agent_label: agentLabel,
    agent_type_id: scalarString(params.agent_type_id),
    agent_role_id: scalarString(params.agent_role_id),
    source_app_id: scalarString(params.source_app_id) || "chat",
    title: threadTitle,
  };
}

export function normalizeChatRouteParams(params: ShellRouteParams): ShellRouteParams {
  const appPage = scalarString(params.app_page);
  if (!appPage) {
    return params;
  }
  const [kind, id] = appPage.split("/").filter(Boolean);
  if (kind === "threads" && id) {
    return { ...params, thread_id: id };
  }
  if (kind === "runtime-sessions" && id) {
    return { ...params, runtime_session_id: id };
  }
  if (kind === "graph" && id) {
    return { ...params, view: "graph", inter_agent_run_id: id };
  }
  return params;
}

export function consumeNewChatRequest(params: ShellRouteParams, consumedRequestIds: Set<string>, consumedLegacyRequest: { current: boolean }): boolean {
  const requestId = scalarString(params.new_chat_request_id);
  if (!requestId) {
    if (consumedLegacyRequest.current) {
      return false;
    }
    consumedLegacyRequest.current = true;
    return true;
  }
  if (consumedRequestIds.has(requestId)) {
    return false;
  }
  consumedRequestIds.add(requestId);
  return true;
}

export function shellMessageMatchesNavigationScope(payload: { navigation_scope?: string }, navigationScope: string): boolean {
  if (navigationScope) {
    return payload.navigation_scope === navigationScope;
  }
  return !payload.navigation_scope;
}

export function chatNavigationRequestKey({
  newChatProjectId,
  requestedRuntimeSessionId,
  requestedThreadId,
  shouldCreateChat,
}: {
  newChatProjectId: string | null;
  requestedRuntimeSessionId: string | null;
  requestedThreadId: string | null;
  shouldCreateChat: boolean;
}) {
  return JSON.stringify({
    new_chat: shouldCreateChat,
    project_id: newChatProjectId || "",
    runtime_session_id: requestedRuntimeSessionId || "",
    thread_id: requestedThreadId || "",
  });
}

export function scalarString(value: string | boolean | null | undefined): string {
  return typeof value === "string" ? value.trim() : "";
}

function decodePathSegment(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}
