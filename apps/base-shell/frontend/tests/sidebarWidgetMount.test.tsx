// @vitest-environment happy-dom

import { act } from "react";
import type { ComponentProps } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AppRegistryItem, SessionUser, WorkspaceItem } from "../src/api";
import { Sidebar } from "../src/components/Sidebar";
import type { WidgetPrimaryActionState } from "../src/components/WidgetSlot";
import type { ShellThemeState } from "../src/theme";

const widgetSlotMock = vi.fn((props: Record<string, unknown>) => {
  void props;
  return <div data-testid="widget-slot" />;
});

vi.mock("../src/components/WidgetSlot", () => ({
  WidgetSlot: (props: Record<string, unknown>) => widgetSlotMock(props),
}));

const shellTheme = {
  color_scheme: "dark",
  effective: "dark",
  mode: "dark",
} satisfies ShellThemeState;

describe("Sidebar widget mount gate", () => {
  let container: HTMLDivElement;
  let root: Root;
  let primaryActionStateChange: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    widgetSlotMock.mockClear();
    primaryActionStateChange = vi.fn();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("does not mount primary or footer widgets while the detail layer is closed", async () => {
    await renderSidebar(root, primaryActionStateChange, { isOpen: false, isPinned: false });

    expect(widgetSlotMock).not.toHaveBeenCalled();
    expect(primaryActionStateChange).toHaveBeenCalledWith({
      available: false,
      label: "",
      preferredSurface: "app",
    });
  });

  it("mounts primary and footer widgets when the detail layer is open", async () => {
    await renderSidebar(root, primaryActionStateChange, { isOpen: true, isPinned: false });

    expect(widgetSlotMock).toHaveBeenCalledTimes(2);
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

async function renderSidebar(
  root: Root,
  primaryActionStateChange: ReturnType<typeof vi.fn>,
  overrides: Partial<ComponentProps<typeof Sidebar>>,
) {
  await act(async () => {
    root.render(
      <Sidebar
        activeAppId="chat"
        activeAppParams={{}}
        activeWorkspaceId="default"
        apps={[app("chat")]}
        isLoading={false}
        isMobileLayout={false}
        isOpen={false}
        isPinned={false}
        mobilePrimaryActionRequestId={0}
        mode="rail"
        onClose={vi.fn()}
        onModeChange={vi.fn()}
        onOpenApp={vi.fn()}
        onOpenSettings={vi.fn()}
        onOpenSidebar={vi.fn()}
        onPrimaryActionStateChange={primaryActionStateChange as (state: WidgetPrimaryActionState) => void}
        onReorderPinnedApps={vi.fn()}
        onSidebarDetailsWidthChange={vi.fn()}
        onThemeModeChange={vi.fn()}
        onWorkspaceChanged={vi.fn()}
        pinnedAppIds={["chat"]}
        railMetrics={{}}
        shellTheme={shellTheme}
        sidebarDetailsWidthPx={360}
        themeMode="dark"
        user={{ platform_role: "admin", username: "admin" } as SessionUser}
        workspaces={[{ workspace_id: "default", name: "Default", description: null, status: "active", governance: {}, quota: {}, is_active: true } as WorkspaceItem]}
        {...overrides}
      />,
    );
    await Promise.resolve();
  });
}
