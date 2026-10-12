export type SettingsPageId =
  | 'users'
  | 'workspace-access'
  | 'workspace-apps'
  | 'app-links'
  | 'models'
  | 'voice'
  | 'computer-use'
  | 'usage'
  | 'sessions'
  | 'learning'
  | 'cache'
  | 'persistence';

export function settingsPageDomKey(workspaceId: string, page: SettingsPageId, userId = '') {
  return `page:${JSON.stringify([workspaceId, page, ['users', 'workspace-access'].includes(page) ? userId : ''])}`;
}

export type SettingsPage = {
  id: SettingsPageId;
  title: string;
  summary: string;
  icon: string;
  group: 'AI' | 'Workspace' | 'System';
  keywords: string;
};

export const SETTINGS_PAGES: SettingsPage[] = [
  { id: 'voice', title: 'Voice', summary: 'Configure speech synthesis and transcription.', icon: 'record_voice_over', group: 'AI', keywords: 'voice speech audio transcription language' },
  { id: 'computer-use', title: 'PC use', summary: 'Choose direct control or a separate interface operator.', icon: 'desktop_windows', group: 'AI', keywords: 'pc computer device operator recovery model' },
  { id: 'usage', title: 'Usage', summary: 'Inspect workspace tokens and provider subscriptions.', icon: 'monitoring', group: 'AI', keywords: 'tokens consumption subscription cost quota history' },
  { id: 'sessions', title: 'Sessions', summary: 'Review runtime sessions and their cleanup scope.', icon: 'terminal', group: 'System', keywords: 'runtime sessions clean delete maintenance server' },
  {
    id: 'users',
    title: 'Users & access',
    summary: 'Create accounts, edit profile details, reset passwords, and remove users.',
    icon: 'manage_accounts', group: 'Workspace', keywords: 'account password profile role access'
  },
  {
    id: 'workspace-access',
    title: 'Workspace access',
    summary: 'Assign the selected user to workspaces and set workspace roles.',
    icon: 'badge', group: 'Workspace', keywords: 'membership workspace permissions'
  },
  {
    id: 'workspace-apps',
    title: 'Workspace apps',
    summary: 'Install, enable, disable, or uninstall app bindings per workspace.',
    icon: 'deployed_code', group: 'Workspace', keywords: 'install enable disable app workspace create'
  },
  {
    id: 'app-links',
    title: 'App links',
    summary: 'Choose provider apps for app interfaces and shared capabilities.',
    icon: 'hub', group: 'Workspace', keywords: 'dependencies interfaces links'
  },
  {
    id: 'models',
    title: 'Models & providers',
    summary: 'Choose default models and configure provider access.',
    icon: 'tune', group: 'AI', keywords: 'default model provider routing credentials reasoning'
  },
  {
    id: 'learning',
    title: 'Conversation learning',
    summary: 'Learn from your chats. Review knowledge and discover better ways to work.',
    icon: 'psychology', group: 'AI', keywords: 'memory conversation learning'
  },
  {
    id: 'cache',
    title: 'Cache',
    summary: 'Inspect aggregate browser cache usage and clear disposable local data.',
    icon: 'cached', group: 'System', keywords: 'browser cache clear'
  },
  {
    id: 'persistence',
    title: 'Persistence',
    summary: 'Inspect and migrate the core control-plane persistence adapter.',
    icon: 'database', group: 'System', keywords: 'persistence migration database'
  }
];

export const DEFAULT_SETTINGS_PAGE_ID: SettingsPageId = 'models';

export function settingsPageById(pageId: string): SettingsPage {
  return SETTINGS_PAGES.find((page) => page.id === pageId) || SETTINGS_PAGES.find((page) => page.id === DEFAULT_SETTINGS_PAGE_ID) || SETTINGS_PAGES[0];
}

export function settingsAppPageFor(pageId: SettingsPageId): string {
  return `pages/${pageId}`;
}

export function settingsPageIdFromParams(params: Record<string, unknown>): SettingsPageId | '' {
  const directPageId =
    normalizeSettingsPageId(scalarParam(params.page_id)) ||
    normalizeSettingsPageId(scalarParam(params.page)) ||
    normalizeSettingsPageId(scalarParam(params.id));
  if (directPageId) {
    return directPageId;
  }

  const appPage = scalarParam(params.app_page);
  if (!appPage) {
    return '';
  }

  const directAppPage = normalizeSettingsPageId(appPage);
  if (directAppPage) {
    return directAppPage;
  }

  const pagesMatch = /^pages\/([^/?#]+)$/.exec(appPage);
  if (pagesMatch?.[1]) {
    return normalizeSettingsPageId(decodeParam(pagesMatch[1]));
  }

  if (/^users(?:\/|$)/.test(appPage)) {
    return 'users';
  }

  const sectionMatch = /^([^/?#]+)(?:\/|$)/.exec(appPage);
  return sectionMatch?.[1] ? normalizeSettingsPageId(decodeParam(sectionMatch[1])) : '';
}

export function normalizeSettingsPageId(value: string): SettingsPageId | '' {
  let normalized = value.trim().toLowerCase().replace(/_/g, '-');
  if (normalized === 'platform-settings') normalized = 'models';
  return SETTINGS_PAGES.some((page) => page.id === normalized) ? normalized as SettingsPageId : '';
}

function scalarParam(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function decodeParam(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}
