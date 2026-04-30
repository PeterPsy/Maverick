type ShellPostTarget = {
  postMessage: (message: unknown, targetOrigin: string) => void;
};

type ShellRouteOptions = {
  currentWindow?: unknown;
  navigationScope?: string;
  origin?: string;
  parentWindow?: ShellPostTarget | null;
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

function postChatRouteToShell(params: Record<string, string>, options: ShellRouteOptions): boolean {
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
      app_id: "chat",
      params,
    },
    origin,
  );
  return true;
}
