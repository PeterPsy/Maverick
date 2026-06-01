// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AppRegistryItem } from "../src/api";
import { MobileShellHeader } from "../src/components/MobileShellHeader";

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

describe("MobileShellHeader", () => {
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

  it("wires sidebar, new chat, and app-owned primary action buttons", async () => {
    const toggleSidebar = vi.fn();
    const togglePinnedApps = vi.fn();
    const closeMobileChat = vi.fn();
    const openMobileChat = vi.fn();
    const openNewChat = vi.fn();
    const primaryAction = vi.fn();

    await act(async () => {
      root.render(
        <MobileShellHeader
          activeApp={app("agents")}
          chatApp={app("chat")}
          isPinnedAppsOpen={false}
          isMobileChatOpen={false}
          isPrimaryActionAvailable={true}
          isSidebarOpen={false}
          showMobileChatAction={true}
          onCloseMobileChat={closeMobileChat}
          onOpenMobileChat={openMobileChat}
          onOpenNewChat={openNewChat}
          onTogglePinnedApps={togglePinnedApps}
          onToggleSidebar={toggleSidebar}
          onPrimaryAction={primaryAction}
          primaryActionLabel="New Agent"
        />,
      );
    });

    const sidebarButton = buttonByLabel(container, "Apri sidebar");
    const pinnedAppsButton = buttonByLabel(container, "Apri applicazioni pinnate");
    const newChatButton = buttonByLabel(container, "Nuova chat");
    const primaryActionButton = buttonByLabel(container, "New Agent");
    const mobileChatButton = buttonByLabel(container, "Apri chat contestuale");

    expect(container.querySelector(".bs-mobile-shell-header__app-logo")).toBeInstanceOf(HTMLElement);
    expect(container.querySelector(".bs-mobile-shell-header__chat-logo")).toBeInstanceOf(HTMLElement);
    expect(container.querySelectorAll(".bs-mobile-shell-header__burger span")).toHaveLength(2);
    expect(primaryActionButton.disabled).toBe(false);

    await act(async () => {
      sidebarButton.click();
      pinnedAppsButton.click();
      newChatButton.click();
      primaryActionButton.click();
      mobileChatButton.click();
    });

    expect(toggleSidebar).toHaveBeenCalledTimes(1);
    expect(togglePinnedApps).toHaveBeenCalledTimes(1);
    expect(openNewChat).toHaveBeenCalledTimes(1);
    expect(primaryAction).toHaveBeenCalledTimes(1);
    expect(openMobileChat).toHaveBeenCalledTimes(1);
    expect(closeMobileChat).not.toHaveBeenCalled();
  });

  it("keeps the primary action disabled until the mounted widget exposes one", async () => {
    const primaryAction = vi.fn();
    const closeMobileChat = vi.fn();

    await act(async () => {
      root.render(
        <MobileShellHeader
          activeApp={null}
          chatApp={app("chat")}
          isPinnedAppsOpen={true}
          isMobileChatOpen={true}
          isPrimaryActionAvailable={false}
          isSidebarOpen={true}
          showMobileChatAction={true}
          onCloseMobileChat={closeMobileChat}
          onOpenMobileChat={vi.fn()}
          onOpenNewChat={vi.fn()}
          onTogglePinnedApps={vi.fn()}
          onToggleSidebar={vi.fn()}
          onPrimaryAction={primaryAction}
          primaryActionLabel=""
        />,
      );
    });

    const primaryActionButton = buttonByLabel(container, "Azione principale");
    const closeChatButton = buttonByLabel(container, "Chiudi chat contestuale");
    expect(buttonByLabel(container, "Chiudi sidebar")).toBeInstanceOf(HTMLButtonElement);
    expect(buttonByLabel(container, "Chiudi applicazioni pinnate")).toBeInstanceOf(HTMLButtonElement);
    expect(closeChatButton.getAttribute("aria-pressed")).toBe("true");
    expect(container.querySelector(".bs-mobile-shell-header.is-obscured")).toBeNull();
    expect(primaryActionButton.disabled).toBe(true);

    await act(async () => {
      primaryActionButton.click();
      closeChatButton.click();
    });

    expect(primaryAction).not.toHaveBeenCalled();
    expect(closeMobileChat).toHaveBeenCalledTimes(1);
  });

  it("hides the contextual floating chat action while Chat is the active app", async () => {
    await act(async () => {
      root.render(
        <MobileShellHeader
          activeApp={app("chat")}
          chatApp={app("chat")}
          isPinnedAppsOpen={false}
          isMobileChatOpen={false}
          isPrimaryActionAvailable={false}
          isSidebarOpen={false}
          showMobileChatAction={false}
          onCloseMobileChat={vi.fn()}
          onOpenMobileChat={vi.fn()}
          onOpenNewChat={vi.fn()}
          onTogglePinnedApps={vi.fn()}
          onToggleSidebar={vi.fn()}
          onPrimaryAction={vi.fn()}
          primaryActionLabel=""
        />,
      );
    });

    expect(container.querySelector('button[aria-label="Apri chat contestuale"]')).toBeNull();
  });
});

function buttonByLabel(parent: HTMLElement, label: string): HTMLButtonElement {
  const button = parent.querySelector(`button[aria-label="${label}"]`);
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error(`Button ${label} was not mounted.`);
  }
  return button;
}
