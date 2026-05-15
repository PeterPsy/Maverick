export type SettingsPageId =
  | 'users'
  | 'workspace-access'
  | 'workspace-apps'
  | 'app-links'
  | 'platform-settings'
  | 'persistence';

export type SettingsPage = {
  id: SettingsPageId;
  title: string;
  summary: string;
  icon: string;
};

export const SETTINGS_PAGES: SettingsPage[] = [
  {
    id: 'users',
    title: 'Users',
    summary: 'Create accounts, edit profile details, reset passwords, and remove users.',
    icon: 'manage_accounts'
  },
  {
    id: 'workspace-access',
    title: 'Workspace access',
    summary: 'Assign the selected user to workspaces and set workspace roles.',
    icon: 'badge'
  },
  {
    id: 'workspace-apps',
    title: 'Workspace apps',
    summary: 'Install, enable, disable, or uninstall app bindings per workspace.',
    icon: 'deployed_code'
  },
  {
    id: 'app-links',
    title: 'App links',
    summary: 'Choose provider apps for intra-app catalogs and cross-app interfaces.',
    icon: 'hub'
  },
  {
    id: 'platform-settings',
    title: 'Platform settings',
    summary: 'Tune the active provider model and clean runtime sessions.',
    icon: 'tune'
  },
  {
    id: 'persistence',
    title: 'Persistence',
    summary: 'Inspect and migrate the core control-plane persistence adapter.',
    icon: 'database'
  }
];

export const DEFAULT_SETTINGS_PAGE_ID: SettingsPageId = 'platform-settings';

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
  const normalized = value.trim().toLowerCase().replace(/_/g, '-');
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
