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
    const openSidebar = vi.fn();
    const openNewChat = vi.fn();
    const primaryAction = vi.fn();

    await act(async () => {
      root.render(
        <MobileShellHeader
          activeApp={app("chat")}
          isPrimaryActionAvailable={true}
          isSidebarOpen={false}
          onOpenNewChat={openNewChat}
          onOpenSidebar={openSidebar}
          onPrimaryAction={primaryAction}
          primaryActionLabel="New Agent"
        />,
      );
    });

    const sidebarButton = buttonByLabel(container, "Apri sidebar");
    const newChatButton = buttonByLabel(container, "Nuova chat");
    const primaryActionButton = buttonByLabel(container, "New Agent");

    expect(container.querySelector(".bs-mobile-shell-header__app-logo")).toBeInstanceOf(HTMLElement);
    expect(primaryActionButton.disabled).toBe(false);

    await act(async () => {
      sidebarButton.click();
      newChatButton.click();
      primaryActionButton.click();
    });

    expect(openSidebar).toHaveBeenCalledTimes(1);
    expect(openNewChat).toHaveBeenCalledTimes(1);
    expect(primaryAction).toHaveBeenCalledTimes(1);
  });

  it("keeps the primary action disabled until the mounted widget exposes one", async () => {
    const primaryAction = vi.fn();

    await act(async () => {
      root.render(
        <MobileShellHeader
          activeApp={null}
          isPrimaryActionAvailable={false}
          isSidebarOpen={true}
          onOpenNewChat={vi.fn()}
          onOpenSidebar={vi.fn()}
          onPrimaryAction={primaryAction}
          primaryActionLabel=""
        />,
      );
    });

    const primaryActionButton = buttonByLabel(container, "Azione principale");
    expect(container.querySelector(".bs-mobile-shell-header.is-obscured")).toBeInstanceOf(HTMLElement);
    expect(primaryActionButton.disabled).toBe(true);

    await act(async () => {
      primaryActionButton.click();
    });

    expect(primaryAction).not.toHaveBeenCalled();
  });
});

function buttonByLabel(parent: HTMLElement, label: string): HTMLButtonElement {
  const button = parent.querySelector(`button[aria-label="${label}"]`);
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error(`Button ${label} was not mounted.`);
  }
  return button;
}
