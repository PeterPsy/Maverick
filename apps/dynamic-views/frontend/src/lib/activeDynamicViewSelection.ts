type ShellPostTarget = {
  postMessage: (message: unknown, targetOrigin: string) => void;
};

type NotifyOptions = {
  currentWindow?: unknown;
  origin?: string;
  parentWindow?: ShellPostTarget | null;
};

export type ActiveDynamicViewSelectionMessage = {
  owner_app_id?: string;
  selection?: Record<string, unknown>;
  type?: string;
};

export function notifyActiveDynamicViewSelection(viewId: string, options: NotifyOptions = {}): boolean {
  const normalizedViewId = viewId.trim();
  if (!normalizedViewId) {
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
      owner_app_id: 'dynamic-views',
      selection: { view_id: normalizedViewId }
    },
    origin
  );
  return true;
}

export function dynamicViewIdFromSelectionMessage(message: ActiveDynamicViewSelectionMessage, ownerAppId = 'dynamic-views'): string {
  if (message.type !== 'maverick.app.selection-changed' || message.owner_app_id !== ownerAppId) {
    return '';
  }
  const selection = message.selection;
  return scalarString(selection?.view_id) || scalarString(selection?.instance_id);
}

function scalarString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}
