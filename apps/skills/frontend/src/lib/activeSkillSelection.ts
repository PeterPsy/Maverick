import { skillIdFromParams } from './skillNavigationParams';

type ShellPostTarget = {
  postMessage: (message: unknown, targetOrigin: string) => void;
};

type NotifyOptions = {
  currentWindow?: unknown;
  origin?: string;
  parentWindow?: ShellPostTarget | null;
};

export type ActiveSkillSelectionMessage = {
  owner_app_id?: string;
  selection?: Record<string, unknown>;
  type?: string;
};

export function notifyActiveSkillSelection(skillId: string, options: NotifyOptions = {}): boolean {
  const normalizedSkillId = skillId.trim();
  if (!normalizedSkillId) {
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
      owner_app_id: 'skills',
      selection: { skill_id: normalizedSkillId }
    },
    origin
  );
  return true;
}

export function skillIdFromSelectionMessage(payload: ActiveSkillSelectionMessage) {
  if (payload.type !== 'maverick.app.selection-changed' || payload.owner_app_id !== 'skills') {
    return '';
  }
  const value = payload.selection && typeof payload.selection.skill_id === 'string' ? payload.selection.skill_id.trim() : '';
  return value;
}

export function skillIdFromWidgetContext(payload: { context?: Record<string, unknown>; type?: string }): string {
  const context = payload.context;
  if (!context) {
    return '';
  }
  const directSkillId = scalarString(context.skill_id);
  if (directSkillId) {
    return directSkillId;
  }
  const content = recordValue(context.content);
  const payloadValue = recordValue(content?.payload);
  const activeAppParams = recordValue(payloadValue?.active_app_params);
  return activeAppParams ? skillIdFromParams(activeAppParams) : '';
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function scalarString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}
