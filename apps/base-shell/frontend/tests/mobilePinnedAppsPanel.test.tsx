// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AppRegistryItem } from "../src/api";
import { MobilePinnedAppsPanel } from "../src/components/MobilePinnedAppsPanel";

function app(app_id: string): AppRegistryItem {
  return {
    app_id,
    backend_mount: "",
    description: "",
    distribution_mode: "sealed",
    frontend_mount: `/apps/${app_id}/`,
    frontend_role: "workspace",
    frontend_launchable: true,
    logo: null,
    name: app_id,
    publisher: "maverick",
    source_access: "none",
    status: "enabled",
    version: "1.0.0",
    provides: [],
    requires: [],
    views: [],
  };
}

describe("MobilePinnedAppsPanel", () => {
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
    vi.clearAllMocks();
  });

  it("renders the desktop rail skeleton pattern while pinned apps are loading", async () => {
    await act(async () => {
      root.render(
        <MobilePinnedAppsPanel
          activeAppId={null}
          apps={[]}
          isOpen={true}
          isLoading={true}
          onOpenApp={vi.fn()}
          onOpenSettings={vi.fn()}
          settingsApp={null}
        />,
      );
    });

    const panel = container.querySelector(".bs-mobile-pinned-apps");
    expect(panel?.getAttribute("aria-busy")).toBe("true");
    expect(panel?.getAttribute("aria-label")).toBe("Caricamento applicazioni");
    expect(container.querySelectorAll(".bs-sidebar__rail-skeleton-logo")).toHaveLength(4);
    expect(container.querySelectorAll(".bs-mobile-pinned-apps__skeleton-name")).toHaveLength(4);
    expect(container.querySelectorAll("button")).toHaveLength(0);
  });

  it("renders app buttons after loading", async () => {
    const openApp = vi.fn();

    await act(async () => {
      root.render(
        <MobilePinnedAppsPanel
          activeAppId="chat"
          apps={[app("chat"), app("agents")]}
          isOpen={true}
          isLoading={false}
          onOpenApp={openApp}
          onOpenSettings={vi.fn()}
          settingsApp={null}
        />,
      );
    });

    const panel = container.querySelector(".bs-mobile-pinned-apps");
    const chatButton = container.querySelector('button[aria-label="chat"]');
    expect(panel?.getAttribute("aria-busy")).toBeNull();
    expect(chatButton?.getAttribute("aria-current")).toBe("page");
    expect(container.querySelectorAll(".bs-sidebar__rail-skeleton-logo")).toHaveLength(0);

    await act(async () => {
      chatButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(openApp).toHaveBeenCalledWith("chat");
  });

  it("renders Settings as a static mobile shortcut outside pinned apps", async () => {
    const openApp = vi.fn();
    const openSettings = vi.fn();

    await act(async () => {
      root.render(
        <MobilePinnedAppsPanel
          activeAppId="settings"
          apps={[app("chat"), app("app-store")]}
          isOpen={true}
          isLoading={false}
          onOpenApp={openApp}
          onOpenSettings={openSettings}
          settingsApp={{ ...app("settings"), name: "Settings" }}
        />,
      );
    });

    const settingsButton = container.querySelector('button[aria-label="Settings"]');
    expect(settingsButton?.getAttribute("aria-current")).toBe("page");
    expect(settingsButton?.textContent).toContain("admin_panel_settings");
    expect(settingsButton?.textContent).toContain("Settings");

    await act(async () => {
      settingsButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(openSettings).toHaveBeenCalledTimes(1);
    expect(openApp).not.toHaveBeenCalledWith("settings");
  });
});
