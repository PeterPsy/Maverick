// @vitest-environment happy-dom

import { act } from "react";
import type { ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AppRegistryItem } from "../src/api";
import { deriveConnectivityState } from "../src/connectivity";
import { LocalContentDialog } from "../src/components/LocalContentDialog";
import { OfflineIndicator } from "../src/components/OfflineIndicator";
import { OfflineWorkspaceShell } from "../src/components/OfflineWorkspaceShell";
import { SidebarAppRail } from "../src/components/SidebarAppRail";

const offline = deriveConnectivityState("offline", "2026-08-26T12:00:00Z");
const update = { applying: false, available: false, buildId: null, recovery: "idle" as const };

describe("offline-aware shell UX", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it.each([
    ["fixed", "expanded"],
    ["rail", "compact"],
  ] as const)("renders exactly one sidebar indicator in %s mode", async (sidebarMode, indicatorMode) => {
    await act(async () => {
      root.render(
        <OfflineWorkspaceShell
          connectivity={offline}
          onOpenLocalContent={vi.fn()}
          sidebarMode={sidebarMode}
          update={update}
        />,
      );
    });

    expect(container.querySelectorAll(".bs-offline-indicator")).toHaveLength(1);
    expect(container.querySelector(`[data-testid="offline-indicator-${indicatorMode}"]`)).toBeInstanceOf(HTMLButtonElement);
    expect(container.querySelector("iframe")).toBeNull();
    expect(container.textContent).not.toContain("Invia prompt");
    expect(container.textContent).toContain("modelli, agenti, tool");
  });

  it("replaces only the active rail app and restores it after confirmed reconnection", async () => {
    const apps = [app("chat"), app("storage")];
    const render = (statusSlot: ReactNode) => (
      <SidebarAppRail
        activeAppId="chat"
        appsToRender={apps}
        enableReorder={false}
        isInitialLoading={false}
        onOpenApp={vi.fn()}
        onOpenSettings={vi.fn()}
        onReorderPinnedApps={vi.fn()}
        settingsApp={null}
        statusSlot={statusSlot}
      />
    );
    await act(async () => {
      root.render(render(<OfflineIndicator connectivity={offline} mode="compact" onOpen={vi.fn()} />));
    });
    expect(container.querySelectorAll(".bs-offline-indicator")).toHaveLength(1);
    expect(container.querySelector('button[aria-label^="chat"]')).toBeNull();
    expect(container.querySelector('button[aria-label="storage"]')).toBeInstanceOf(HTMLButtonElement);

    await act(async () => { root.render(render(null)); });
    expect(container.querySelector(".bs-offline-indicator")).toBeNull();
    expect(container.querySelector('button[aria-label^="chat"]')).toBeInstanceOf(HTMLButtonElement);
  });

  it("exposes stale local metadata and the waiting update from the same management surface", async () => {
    const stale = deriveConnectivityState("offline", "2026-08-20T12:00:00Z", Date.parse("2026-08-26T12:00:00Z"));
    const onApplyUpdate = vi.fn();
    await act(async () => {
      root.render(
        <LocalContentDialog
          connectivity={stale}
          onApplyUpdate={onApplyUpdate}
          onClose={vi.fn()}
          onRecover={vi.fn()}
          onRetry={vi.fn()}
          open
          update={{ ...update, available: true, buildId: "next-build" }}
        />,
      );
    });

    const dialog = document.body.querySelector('[role="dialog"]');
    expect(dialog?.textContent).toContain("Scaduto");
    expect(dialog?.textContent).toContain("Dispositivo");
    expect(dialog?.textContent).toContain("Aggiornamento della shell disponibile");
    const updateButton = [...(dialog?.querySelectorAll("button") || [])].find((button) => button.textContent === "Aggiorna");
    await act(async () => { updateButton?.click(); });
    expect(onApplyUpdate).toHaveBeenCalledOnce();
  });

  it("renders an available update as a status in the current-app slot", async () => {
    const online = deriveConnectivityState("online", "2026-08-26T12:00:00Z");
    await act(async () => {
      root.render(<OfflineIndicator connectivity={online} mode="expanded" onOpen={vi.fn()} updateAvailable />);
    });
    expect(container.textContent).toContain("Aggiornamento disponibile");
    expect(container.querySelectorAll(".bs-offline-indicator")).toHaveLength(1);
  });
});

function app(appId: string): AppRegistryItem {
  return {
    app_id: appId,
    backend_mount: "",
    description: "",
    distribution_mode: "sealed",
    frontend_launchable: true,
    frontend_mount: `/apps/${appId}/`,
    frontend_role: "workspace",
    logo: null,
    name: appId,
    provides: [],
    publisher: "maverick",
    requires: [],
    source_access: "none",
    status: "enabled",
    version: "1.0.0",
    views: [],
  };
}
