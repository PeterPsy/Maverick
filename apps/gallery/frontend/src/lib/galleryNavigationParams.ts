export type GalleryNavigationParams = Record<string, string | boolean | null | undefined>;

export type GalleryNavigationTarget = {
  fileId: string;
  workspaceRelativePath: string;
};

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

export function galleryTargetFromParams(params: GalleryNavigationParams): GalleryNavigationTarget | null {
  const fileId = scalarString(params.file_id);
  const workspaceRelativePath = scalarString(params.workspace_relative_path) || scalarString(params.path);
  if (fileId || workspaceRelativePath) {
    return { fileId, workspaceRelativePath };
  }
  const appPage = scalarString(params.app_page);
  const match = /^files\/(.+)$/.exec(appPage);
  if (!match?.[1]) {
    return null;
  }
  return { fileId: decodeParam(match[1]), workspaceRelativePath: '' };
}

export function galleryTargetFromWidgetContext(message: WidgetContextMessage): GalleryNavigationTarget | null {
  if (message.type !== 'maverick.widget.context-changed') {
    return null;
  }
  const payload = message.context?.content?.payload;
  if (!payload || typeof payload !== 'object') {
    return null;
  }
  const activeAppId = scalarString((payload as { active_app_id?: unknown }).active_app_id);
  if (activeAppId !== 'gallery') {
    return null;
  }
  const activeAppParams = (payload as { active_app_params?: unknown }).active_app_params;
  if (!activeAppParams || typeof activeAppParams !== 'object' || Array.isArray(activeAppParams)) {
    return null;
  }
  return galleryTargetFromParams(activeAppParams as GalleryNavigationParams);
}

function decodeParam(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}
