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
          onWorkspaceChange={() => undefined}
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

  it("switches existing workspaces without offering workspace creation", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    const onWorkspaceChange = vi.fn().mockResolvedValue(undefined);
    const prompt = vi.fn();
    vi.stubGlobal("prompt", prompt);

    act(() => {
      root.render(
        <WorkspaceSwitcher
          activeWorkspaceId="default"
          onWorkspaceChange={onWorkspaceChange}
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

    expect(container.querySelector("button")).toBeNull();
    expect(prompt).not.toHaveBeenCalled();

    act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });
});
