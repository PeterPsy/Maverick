/** @vitest-environment happy-dom */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ComposerActions } from "./ComposerActions";

let root: Root | null = null;
let container: HTMLDivElement | null = null;

async function renderActions(canSend = true) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  const onSubmit = vi.fn();
  const onStopTurn = vi.fn();
  await act(async () => {
    root!.render(<ComposerActions canSend={canSend} canStopTurn onSubmit={onSubmit} onStopTurn={onStopTurn} />);
  });
  return { onSubmit, onStopTurn };
}

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  root = null;
  container = null;
});

describe("composer action pointer focus", () => {
  for (const label of ["Send message", "Stop chat"]) {
    for (const pointerType of ["mouse", "touch"]) {
      it(`keeps ${label} stable on ${pointerType} down and acts only on click`, async () => {
        const { onSubmit, onStopTurn } = await renderActions();
        const button = container!.querySelector<HTMLButtonElement>(`[aria-label="${label}"]`)!;
        const pointerDown = new PointerEvent("pointerdown", { bubbles: true, cancelable: true, pointerType });

        button.dispatchEvent(pointerDown);

        expect(pointerDown.defaultPrevented).toBe(true);
        expect(onSubmit).not.toHaveBeenCalled();
        expect(onStopTurn).not.toHaveBeenCalled();

        button.click();

        expect(label === "Send message" ? onSubmit : onStopTurn).toHaveBeenCalledTimes(1);
        expect(label === "Send message" ? onStopTurn : onSubmit).not.toHaveBeenCalled();
      });
    }

    it(`keeps ${label} focusable independently of pointer handling`, async () => {
      await renderActions();
      const button = container!.querySelector<HTMLButtonElement>(`[aria-label="${label}"]`)!;

      button.focus();

      expect(document.activeElement).toBe(button);
      expect(button.type).toBe("button");
    });
  }

  it("does not enable submission when the composer cannot send", async () => {
    const { onSubmit } = await renderActions(false);
    const button = container!.querySelector<HTMLButtonElement>('[aria-label="Send message"]')!;

    button.click();

    expect(button.disabled).toBe(true);
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
