const SESSION_KEY = "maverick:base-shell:session";

export type SidebarMode = "rail" | "fixed";

export type ShellSession = {
  activeAppId: string | null;
  isSidebarOpen: boolean;
  sidebarMode: SidebarMode;
};

const DEFAULT_SESSION: ShellSession = {
  activeAppId: "chat",
  isSidebarOpen: false,
  sidebarMode: "rail",
};

function canUseStorage(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

export function readShellSession(): ShellSession {
  if (!canUseStorage()) {
    return DEFAULT_SESSION;
  }
  try {
    const parsed = JSON.parse(window.localStorage.getItem(SESSION_KEY) || "{}") as Partial<ShellSession>;
    return {
      activeAppId: typeof parsed.activeAppId === "string" && parsed.activeAppId.trim() ? parsed.activeAppId.trim() : DEFAULT_SESSION.activeAppId,
      isSidebarOpen: typeof parsed.isSidebarOpen === "boolean" ? parsed.isSidebarOpen : DEFAULT_SESSION.isSidebarOpen,
      sidebarMode: normalizeSidebarMode(parsed.sidebarMode),
    };
  } catch {
    return DEFAULT_SESSION;
  }
}

export function writeShellSession(session: ShellSession): void {
  if (!canUseStorage()) {
    return;
  }
  window.localStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

function normalizeSidebarMode(value: unknown): SidebarMode {
  return value === "fixed" || value === "rail" ? value : DEFAULT_SESSION.sidebarMode;
}
