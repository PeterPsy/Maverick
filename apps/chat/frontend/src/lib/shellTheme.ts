import { purgeLegacyChatCaches } from './legacyCacheCleanup';
export type LoopinoEffectiveTheme = "dark" | "light";
export type LoopinoThemeMode = LoopinoEffectiveTheme | "system";

export type LoopinoShellTheme = {
  color_scheme: LoopinoEffectiveTheme;
  effective: LoopinoEffectiveTheme;
  mode: LoopinoThemeMode;
};

const DEFAULT_THEME: LoopinoShellTheme = {
  color_scheme: "dark",
  effective: "dark",
  mode: "dark",
};

export function applyInitialLoopinoTheme(): LoopinoShellTheme {
  purgeLegacyChatCaches();
  const theme = themeFromLocation();
  applyLoopinoTheme(theme);
  return theme;
}

export function listenForLoopinoThemeMessages(): () => void {
  function handleMessage(event: MessageEvent) {
    if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
      return;
    }
    const theme = themeFromMessage(event.data);
    if (theme) {
      applyLoopinoTheme(theme);
    }
  }

  window.addEventListener("message", handleMessage);
  return () => window.removeEventListener("message", handleMessage);
}

export function applyLoopinoTheme(theme: LoopinoShellTheme, documentRef: Document = document): void {
  const root = documentRef.documentElement;
  root.dataset.loopinoTheme = theme.effective;
  root.dataset.theme = theme.effective;
  root.style.colorScheme = theme.color_scheme;
}

export function themeFromMessage(message: unknown): LoopinoShellTheme | null {
  if (!message || typeof message !== "object") {
    return null;
  }
  const payload = message as { context?: unknown; theme?: unknown; type?: string };
  if (payload.type === "loopino.shell.theme-changed" || payload.type === "loopino.app.navigate") {
    return normalizeLoopinoTheme(payload.theme);
  }
  if (payload.type === "loopino.widget.context-changed") {
    const contextTheme = themeFromWidgetContext(payload.context);
    return contextTheme ? normalizeLoopinoTheme(contextTheme) : null;
  }
  return null;
}

export function themeFromLocation(locationRef: Location = window.location): LoopinoShellTheme {
  const searchParams = new URLSearchParams(locationRef.search);
  const hashParams = new URLSearchParams(locationRef.hash.startsWith("#") ? locationRef.hash.slice(1) : locationRef.hash);
  return normalizeLoopinoTheme({
    color_scheme: searchParams.get("loopino_color_scheme") || hashParams.get("loopino_color_scheme"),
    effective: searchParams.get("loopino_theme") || hashParams.get("loopino_theme"),
    mode: searchParams.get("loopino_theme_mode") || hashParams.get("loopino_theme_mode"),
  }) || DEFAULT_THEME;
}

export function normalizeLoopinoTheme(value: unknown): LoopinoShellTheme | null {
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

function normalizedEffectiveTheme(value: unknown): LoopinoEffectiveTheme | null {
  return value === "dark" || value === "light" ? value : null;
}

function normalizedThemeMode(value: unknown): LoopinoThemeMode | null {
  return value === "dark" || value === "light" || value === "system" ? value : null;
}
