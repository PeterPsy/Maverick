const SESSION_KEY = "maverick3:base-shell:session";

export type ShellSession = {
  activeAppId: string | null;
  isSidebarOpen: boolean;
  pinnedAppIds: string[];
};

const DEFAULT_SESSION: ShellSession = {
  activeAppId: "chat",
  isSidebarOpen: true,
  pinnedAppIds: ["chat"],
};

function canUseStorage(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function sanitizePinnedAppIds(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return DEFAULT_SESSION.pinnedAppIds;
  }
  return Array.from(new Set(value.filter((item): item is string => typeof item === "string" && item.trim().length > 0).map((item) => item.trim())));
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
      pinnedAppIds: sanitizePinnedAppIds(parsed.pinnedAppIds),
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
