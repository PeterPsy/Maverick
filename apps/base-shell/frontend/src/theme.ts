export type ShellEffectiveTheme = "dark" | "light";
export type ShellThemeMode = ShellEffectiveTheme | "system";

export type ShellThemeState = {
  color_scheme: ShellEffectiveTheme;
  effective: ShellEffectiveTheme;
  mode: ShellThemeMode;
};

export const DEFAULT_SHELL_THEME_MODE: ShellThemeMode = "dark";
export const DEFAULT_SHELL_THEME_STATE: ShellThemeState = {
  color_scheme: "dark",
  effective: "dark",
  mode: DEFAULT_SHELL_THEME_MODE,
};
export const SHELL_SESSION_STORAGE_KEY = "maverick:base-shell:session";

const LIGHT_SCHEME_QUERY = "(prefers-color-scheme: light)";

export function normalizeShellThemeMode(value: unknown): ShellThemeMode {
  return value === "dark" || value === "light" || value === "system" ? value : DEFAULT_SHELL_THEME_MODE;
}

export function readSystemColorScheme(): ShellEffectiveTheme {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return DEFAULT_SHELL_THEME_STATE.effective;
  }
  return window.matchMedia(LIGHT_SCHEME_QUERY).matches ? "light" : "dark";
}

export function resolveShellEffectiveTheme(
  mode: ShellThemeMode,
  systemColorScheme: ShellEffectiveTheme = readSystemColorScheme(),
): ShellEffectiveTheme {
  return mode === "system" ? systemColorScheme : mode;
}

export function createShellThemeState(
  mode: ShellThemeMode,
  systemColorScheme: ShellEffectiveTheme = readSystemColorScheme(),
): ShellThemeState {
  const normalizedMode = normalizeShellThemeMode(mode);
  const effective = resolveShellEffectiveTheme(normalizedMode, systemColorScheme);
  return {
    color_scheme: effective,
    effective,
    mode: normalizedMode,
  };
}

export function readInitialShellThemeMode(): ShellThemeMode {
  if (typeof window === "undefined" || typeof window.localStorage === "undefined") {
    return DEFAULT_SHELL_THEME_MODE;
  }
  try {
    const parsed = JSON.parse(window.localStorage.getItem(SHELL_SESSION_STORAGE_KEY) || "{}") as { themeMode?: unknown };
    return normalizeShellThemeMode(parsed.themeMode);
  } catch {
    return DEFAULT_SHELL_THEME_MODE;
  }
}

export function applyShellThemeToDocument(theme: ShellThemeState, documentRef: Document = document): void {
  const root = documentRef.documentElement;
  root.dataset.maverickTheme = theme.effective;
  root.dataset.theme = theme.effective;
  root.style.colorScheme = theme.color_scheme;
}

export function applyInitialShellTheme(): ShellThemeState {
  const theme = createShellThemeState(readInitialShellThemeMode());
  if (typeof document !== "undefined") {
    applyShellThemeToDocument(theme);
  }
  return theme;
}

export function shellThemeSearchParams(theme: ShellThemeState): Record<string, string> {
  return {
    maverick_color_scheme: theme.color_scheme,
    maverick_theme: theme.effective,
    maverick_theme_mode: theme.mode,
  };
}

export function urlWithShellThemeSearchParams(frontendMount: string, theme: ShellThemeState): URL {
  const url = new URL(frontendMount, window.location.origin);
  const params = shellThemeSearchParams(theme);
  Object.entries(params).forEach(([key, value]) => url.searchParams.set(key, value));
  return url;
}

export function shellThemeMessage(theme: ShellThemeState) {
  return {
    type: "maverick.shell.theme-changed",
    theme,
  };
}

export function shellThemeSignature(theme: ShellThemeState): string {
  return `${theme.mode}:${theme.effective}`;
}
