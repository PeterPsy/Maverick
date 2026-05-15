type ShellPostTarget = {
  postMessage: (message: unknown, targetOrigin: string) => void;
};

type ShellRouteOptions = {
  currentWindow?: unknown;
  navigationScope?: string;
  origin?: string;
  parentWindow?: ShellPostTarget | null;
};
type ShellRouteParams = Record<string, string | boolean | null>;

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

export function openStoragePathInShell(workspaceRelativePath: string, options: ShellRouteOptions = {}): boolean {
  const normalizedPath = workspaceRelativePath.trim();
  if (!normalizedPath) {
    return false;
  }
  return postAppRouteToShell("storage", { workspace_relative_path: normalizedPath }, options);
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
  const origin = options.origin ?? (typeof window === "undefined" ? "*" : window.location.origin);
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
