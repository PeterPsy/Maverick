export type DynamicViewNavigationParams = Record<string, string | boolean | null | undefined>;

export type WidgetContextMessage = {
  context?: {
    content?: {
      payload?: unknown;
    };
  };
  type?: string;
};

export function scalarString(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value.trim() : '';
}

export function dynamicViewIdFromParams(params: DynamicViewNavigationParams): string {
  const directViewId = scalarString(params.view_id) || scalarString(params.instance_id) || scalarString(params.id);
  if (directViewId) {
    return directViewId;
  }
  const appPage = scalarString(params.app_page);
  const match = /^views\/([^/?#]+)$/.exec(appPage);
  if (!match?.[1]) {
    return '';
  }
  return decodeParam(match[1]);
}

export function dynamicViewIdFromWidgetContext(message: WidgetContextMessage): string {
  if (message.type !== 'maverick.widget.context-changed') {
    return '';
  }
  const payload = message.context?.content?.payload;
  if (!payload || typeof payload !== 'object') {
    return '';
  }
  const activeAppId = scalarString((payload as { active_app_id?: unknown }).active_app_id);
  if (activeAppId !== 'dynamic-views') {
    return '';
  }
  const activeAppParams = (payload as { active_app_params?: unknown }).active_app_params;
  if (!activeAppParams || typeof activeAppParams !== 'object' || Array.isArray(activeAppParams)) {
    return '';
  }
  return dynamicViewIdFromParams(activeAppParams as DynamicViewNavigationParams);
}

function decodeParam(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}
