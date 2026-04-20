const SESSION_KEY = "maverick3:base-shell:session";

export type ShellSession = {
  activeAppId: string | null;
  isSidebarOpen: boolean;
};

const DEFAULT_SESSION: ShellSession = {
  activeAppId: "chat",
  isSidebarOpen: true,
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
