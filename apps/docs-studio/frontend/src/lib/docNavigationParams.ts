export type DocNavigationParams = Record<string, string | boolean | null | undefined>;

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

export function docPageIdFromParams(params: DocNavigationParams): string {
  const directPageId = scalarString(params.page_id);
  if (directPageId) {
    return directPageId;
  }
  const appPage = scalarString(params.app_page).replace(/^\/+|\/+$/g, '');
  const match = /^pages\/([^/]+)$/.exec(appPage);
  return match?.[1] || '';
}

export function docPageIdFromWidgetContext(message: WidgetContextMessage): string {
  if (message.type !== 'maverick.widget.context-changed') {
    return '';
  }
  const payload = message.context?.content?.payload;
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return '';
  }
  const activeAppId = scalarString((payload as { active_app_id?: unknown }).active_app_id);
  if (activeAppId !== 'docs-studio') {
    return '';
  }
  const activeAppParams = (payload as { active_app_params?: unknown }).active_app_params;
  if (!activeAppParams || typeof activeAppParams !== 'object' || Array.isArray(activeAppParams)) {
    return '';
  }
  return docPageIdFromParams(activeAppParams as DocNavigationParams);
}
