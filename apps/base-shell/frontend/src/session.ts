const SESSION_KEY = "maverick:base-shell:session";

export type SidebarMode = "rail" | "fixed";

export type ShellSession = {
  activeAppId: string | null;
  isSidebarOpen: boolean;
  sidebarDetailsWidthPx: number;
  sidebarMode: SidebarMode;
};

export const DEFAULT_SIDEBAR_DETAILS_WIDTH_PX = 320;
export const MIN_SIDEBAR_DETAILS_WIDTH_PX = 288;
export const MAX_SIDEBAR_DETAILS_WIDTH_PX = 560;

const DEFAULT_SESSION: ShellSession = {
  activeAppId: "chat",
  isSidebarOpen: false,
  sidebarDetailsWidthPx: DEFAULT_SIDEBAR_DETAILS_WIDTH_PX,
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
      sidebarDetailsWidthPx: normalizeSidebarDetailsWidth(parsed.sidebarDetailsWidthPx),
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

export function resolveInitialSidebarOpen(
  session: ShellSession,
  {
    isInitialChatLaunch,
    isMobileLayout,
  }: {
    isInitialChatLaunch: boolean;
    isMobileLayout: boolean;
  },
): boolean {
  if (isInitialChatLaunch || isMobileLayout) {
    return false;
  }
  return session.sidebarMode === "fixed" ? true : session.isSidebarOpen;
}

function normalizeSidebarMode(value: unknown): SidebarMode {
  return value === "fixed" || value === "rail" ? value : DEFAULT_SESSION.sidebarMode;
}

export function normalizeSidebarDetailsWidth(value: unknown, viewportWidth = currentViewportWidth()): number {
  const parsed = typeof value === "number" ? value : Number.parseFloat(String(value));
  if (!Number.isFinite(parsed)) {
    return clampSidebarDetailsWidth(DEFAULT_SIDEBAR_DETAILS_WIDTH_PX, viewportWidth);
  }
  return clampSidebarDetailsWidth(parsed, viewportWidth);
}

export function clampSidebarDetailsWidth(value: number, viewportWidth = currentViewportWidth()): number {
  const viewportMax = Number.isFinite(viewportWidth) && viewportWidth > 0
    ? Math.max(MIN_SIDEBAR_DETAILS_WIDTH_PX, viewportWidth - 540)
    : MAX_SIDEBAR_DETAILS_WIDTH_PX;
  const maxWidth = Math.min(MAX_SIDEBAR_DETAILS_WIDTH_PX, viewportMax);
  return Math.round(Math.min(Math.max(value, MIN_SIDEBAR_DETAILS_WIDTH_PX), maxWidth));
}

function currentViewportWidth(): number {
  if (typeof window === "undefined") {
    return MAX_SIDEBAR_DETAILS_WIDTH_PX + 540;
  }
  return window.visualViewport?.width ?? window.innerWidth;
}
