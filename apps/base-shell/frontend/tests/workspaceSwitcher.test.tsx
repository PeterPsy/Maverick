// @vitest-environment happy-dom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

import { WorkspaceSwitcher } from "../src/components/WorkspaceSwitcher";

describe("WorkspaceSwitcher", () => {
  it("keeps the active workspace selectable when registry loading fails", () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);

    act(() => {
      root.render(
        <WorkspaceSwitcher
          activeWorkspaceId="default"
          canCreateWorkspace={false}
          onWorkspaceChange={() => undefined}
          onWorkspaceCreate={() => undefined}
          workspaces={[]}
        />,
      );
    });

    const select = container.querySelector<HTMLSelectElement>("#bs-workspace-select");
    expect(select?.value).toBe("default");
    expect(Array.from(select?.options ?? []).map((option) => option.text)).toEqual(["default"]);

    act(() => root.unmount());
    container.remove();
  });

  it("delegates workspace mutations to the shell owner", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    const onWorkspaceChange = vi.fn().mockResolvedValue(undefined);
    const onWorkspaceCreate = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("prompt", vi.fn(() => " New workspace "));

    act(() => {
      root.render(
        <WorkspaceSwitcher
          activeWorkspaceId="default"
          canCreateWorkspace
          onWorkspaceChange={onWorkspaceChange}
          onWorkspaceCreate={onWorkspaceCreate}
          workspaces={[
            {
              workspace_id: "default",
              name: "Default",
              description: null,
              status: "active",
              governance: {},
              quota: {},
              is_active: true,
            },
            {
              workspace_id: "other",
              name: "Other",
              description: null,
              status: "active",
              governance: {},
              quota: {},
              is_active: false,
            },
          ]}
        />,
      );
    });

    const select = container.querySelector<HTMLSelectElement>("#bs-workspace-select")!;
    await act(async () => {
      select.value = "other";
      select.dispatchEvent(new Event("change", { bubbles: true }));
      await Promise.resolve();
    });
    expect(onWorkspaceChange).toHaveBeenCalledOnce();
    expect(onWorkspaceChange).toHaveBeenCalledWith("other");

    await act(async () => {
      container.querySelector<HTMLButtonElement>("[aria-label='Crea workspace']")?.click();
      await Promise.resolve();
    });
    expect(onWorkspaceCreate).toHaveBeenCalledOnce();
    expect(onWorkspaceCreate).toHaveBeenCalledWith("New workspace");

    act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });
});
