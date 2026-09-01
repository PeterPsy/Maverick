type ShellPostTarget = {
  postMessage: (message: unknown, targetOrigin: string) => void;
};

type NotifyOptions = {
  currentWindow?: unknown;
  origin?: string;
  parentWindow?: ShellPostTarget | null;
};

export type ActiveDocSelectionMessage = {
  owner_app_id?: string;
  selection?: Record<string, unknown>;
  type?: string;
};

export function notifyActiveDocSelection(pageId: string, options: NotifyOptions = {}): boolean {
  const normalizedPageId = pageId.trim();
  if (!normalizedPageId) {
    return false;
  }
  const currentWindow = options.currentWindow ?? (typeof window === 'undefined' ? null : window);
  const parentWindow = options.parentWindow ?? (typeof window === 'undefined' ? null : window.parent);
  if (!parentWindow || parentWindow === currentWindow) {
    return false;
  }
  const origin = options.origin ?? '*';
  parentWindow.postMessage(
    {
      type: 'maverick.app.selection-changed',
      owner_app_id: 'docs-studio',
      selection: { page_id: normalizedPageId }
    },
    origin
  );
  return true;
}

export function docPageIdFromSelectionMessage(message: ActiveDocSelectionMessage): string {
  if (message.type !== 'maverick.app.selection-changed' || message.owner_app_id !== 'docs-studio') {
    return '';
  }
  const selection = message.selection;
  return selection && typeof selection.page_id === 'string' ? selection.page_id.trim() : '';
}
