// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ScheduledBlock } from "../../api/scheduledChats";
import { BlockInspector } from "./BlockInspector";

let container: HTMLDivElement;
let root: Root;
const change = vi.fn();
const block: ScheduledBlock = { id: "a", title: "A", instructions: "Do A", skill_ids: ["old-skill"], position: { x: 0, y: 0 } };

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  change.mockReset();
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

async function render(selected: ScheduledBlock) {
  await act(async () => root.render(<BlockInspector block={selected} graph={{ nodes: [selected], edges: [] }}
    locked={false} busy={false} onChange={change} onClose={() => {}} onDelete={() => {}} onRetry={() => {}} />));
}

function skillInput() { return container.querySelectorAll("input")[1]; }

it("shows refreshed skill IDs and clears them when the agent removes them", async () => {
  await render(block);
  await render({ ...block, skill_ids: ["new-skill", "review"] });
  expect(skillInput().value).toBe("new-skill, review");
  await render({ ...block, skill_ids: [] });
  expect(skillInput().value).toBe("");
});

it("preserves a trailing comma while the parent echoes parsed IDs during typing", async () => {
  await render(block);
  const input = skillInput();
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "old-skill, ");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(change).toHaveBeenCalledWith(expect.objectContaining({ skill_ids: ["old-skill"] }));
  await render({ ...block, skill_ids: ["old-skill"] });
  expect(skillInput().value).toBe("old-skill, ");
});
