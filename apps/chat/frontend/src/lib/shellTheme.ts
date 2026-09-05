import { purgeLegacyChatCaches } from './legacyCacheCleanup';
export type MaverickEffectiveTheme = "dark" | "light";
export type MaverickThemeMode = MaverickEffectiveTheme | "system";

export type MaverickShellTheme = {
  color_scheme: MaverickEffectiveTheme;
  effective: MaverickEffectiveTheme;
  mode: MaverickThemeMode;
};

const DEFAULT_THEME: MaverickShellTheme = {
  color_scheme: "dark",
  effective: "dark",
  mode: "dark",
};

export function applyInitialMaverickTheme(): MaverickShellTheme {
  purgeLegacyChatCaches();
  const theme = themeFromLocation();
  applyMaverickTheme(theme);
  return theme;
}

export function listenForMaverickThemeMessages(): () => void {
  function handleMessage(event: MessageEvent) {
    if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
      return;
    }
    const theme = themeFromMessage(event.data);
    if (theme) {
      applyMaverickTheme(theme);
    }
  }

  window.addEventListener("message", handleMessage);
  return () => window.removeEventListener("message", handleMessage);
}

export function applyMaverickTheme(theme: MaverickShellTheme, documentRef: Document = document): void {
  const root = documentRef.documentElement;
  root.dataset.maverickTheme = theme.effective;
  root.dataset.theme = theme.effective;
  root.style.colorScheme = theme.color_scheme;
}

export function themeFromMessage(message: unknown): MaverickShellTheme | null {
  if (!message || typeof message !== "object") {
    return null;
  }
  const payload = message as { context?: unknown; theme?: unknown; type?: string };
  if (payload.type === "maverick.shell.theme-changed" || payload.type === "maverick.app.navigate") {
    return normalizeMaverickTheme(payload.theme);
  }
  if (payload.type === "maverick.widget.context-changed") {
    const contextTheme = themeFromWidgetContext(payload.context);
    return contextTheme ? normalizeMaverickTheme(contextTheme) : null;
  }
  return null;
}

export function themeFromLocation(locationRef: Location = window.location): MaverickShellTheme {
  const searchParams = new URLSearchParams(locationRef.search);
  const hashParams = new URLSearchParams(locationRef.hash.startsWith("#") ? locationRef.hash.slice(1) : locationRef.hash);
  return normalizeMaverickTheme({
    color_scheme: searchParams.get("maverick_color_scheme") || hashParams.get("maverick_color_scheme"),
    effective: searchParams.get("maverick_theme") || hashParams.get("maverick_theme"),
    mode: searchParams.get("maverick_theme_mode") || hashParams.get("maverick_theme_mode"),
  }) || DEFAULT_THEME;
}

export function normalizeMaverickTheme(value: unknown): MaverickShellTheme | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const payload = value as { color_scheme?: unknown; effective?: unknown; mode?: unknown };
  const effective = normalizedEffectiveTheme(payload.effective) || normalizedEffectiveTheme(payload.color_scheme);
  if (!effective) {
    return null;
  }
  return {
    color_scheme: effective,
    effective,
    mode: normalizedThemeMode(payload.mode) || effective,
  };
}

function themeFromWidgetContext(context: unknown): unknown {
  if (!context || typeof context !== "object") {
    return null;
  }
  const contextRecord = context as { content?: unknown; shell_theme?: unknown };
  if (contextRecord.shell_theme) {
    return contextRecord.shell_theme;
  }
  const content = contextRecord.content && typeof contextRecord.content === "object"
    ? (contextRecord.content as { shell_theme?: unknown })
    : null;
  return content?.shell_theme || null;
}

function normalizedEffectiveTheme(value: unknown): MaverickEffectiveTheme | null {
  return value === "dark" || value === "light" ? value : null;
}

function normalizedThemeMode(value: unknown): MaverickThemeMode | null {
  return value === "dark" || value === "light" || value === "system" ? value : null;
}
