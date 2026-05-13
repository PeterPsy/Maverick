import { checklistIdFromParams } from './checklistNavigationParams';

type ShellPostTarget = {
  postMessage: (message: unknown, targetOrigin: string) => void;
};

type NotifyOptions = {
  currentWindow?: unknown;
  origin?: string;
  parentWindow?: ShellPostTarget | null;
};

export type ActiveChecklistSelectionMessage = {
  owner_app_id?: string;
  selection?: Record<string, unknown>;
  type?: string;
};

export function notifyActiveChecklistSelection(checklistId: string, options: NotifyOptions = {}): boolean {
  const normalizedChecklistId = checklistId.trim();
  if (!normalizedChecklistId) {
    return false;
  }
  const currentWindow = options.currentWindow ?? (typeof window === 'undefined' ? null : window);
  const parentWindow = options.parentWindow ?? (typeof window === 'undefined' ? null : window.parent);
  if (!parentWindow || parentWindow === currentWindow) {
    return false;
  }
  const origin = options.origin ?? (typeof window === 'undefined' ? '*' : window.location.origin);
  parentWindow.postMessage(
    {
      type: 'maverick.app.selection-changed',
      owner_app_id: 'checklist',
      selection: { checklist_id: normalizedChecklistId }
    },
    origin
  );
  return true;
}

export function checklistIdFromSelectionMessage(payload: ActiveChecklistSelectionMessage) {
  if (payload.type !== 'maverick.app.selection-changed' || payload.owner_app_id !== 'checklist') {
    return '';
  }
  const value = payload.selection && typeof payload.selection.checklist_id === 'string' ? payload.selection.checklist_id.trim() : '';
  return value;
}

export function checklistIdFromWidgetContext(payload: { context?: Record<string, unknown>; type?: string }): string {
  const context = payload.context;
  if (!context) {
    return '';
  }
  const directChecklistId = scalarString(context.checklist_id);
  if (directChecklistId) {
    return directChecklistId;
  }
  const content = recordValue(context.content);
  const payloadValue = recordValue(content?.payload);
  const activeAppParams = recordValue(payloadValue?.active_app_params);
  return activeAppParams ? checklistIdFromParams(activeAppParams) : '';
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function scalarString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

