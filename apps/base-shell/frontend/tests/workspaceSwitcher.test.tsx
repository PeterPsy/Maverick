// @vitest-environment happy-dom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

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
          onChanged={() => undefined}
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
});
