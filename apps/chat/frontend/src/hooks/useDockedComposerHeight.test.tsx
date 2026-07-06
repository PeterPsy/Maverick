/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useDockedComposerHeight } from "./useDockedComposerHeight";

let root: Root | null = null;
let container: HTMLDivElement | null = null;
let getBoundingClientRectSpy: ReturnType<typeof vi.spyOn> | null = null;

afterEach(() => {
  root?.unmount();
  root = null;
  container?.remove();
  container = null;
  getBoundingClientRectSpy?.mockRestore();
  getBoundingClientRectSpy = null;
});

describe("useDockedComposerHeight", () => {
  it("remeasures the composer dock after graph view unmounts and remounts it", async () => {
    getBoundingClientRectSpy = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockImplementation(function (this: HTMLElement) {
        const height = Number(this.dataset.height || "0");
        return {
          bottom: height,
          height,
          left: 0,
          right: 0,
          top: 0,
          width: 0,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        } as DOMRect;
      });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<ComposerHeightHarness dockHeight={180} isComposerDockVisible />);
    });
    expect(overlayHeight()).toBe("180px");

    await act(async () => {
      root?.render(<ComposerHeightHarness dockHeight={320} isComposerDockVisible={false} />);
    });
    expect(overlayHeight()).toBe("");

    await act(async () => {
      root?.render(<ComposerHeightHarness dockHeight={320} isComposerDockVisible />);
    });
    expect(overlayHeight()).toBe("320px");
  });
});

function ComposerHeightHarness({
  dockHeight,
  isComposerDockVisible,
}: {
  dockHeight: number;
  isComposerDockVisible: boolean;
}) {
  const { chatMainStyle, dockedComposerRef } = useDockedComposerHeight({
    attachmentCount: 0,
    composerError: null,
    isComposerDockVisible,
    isEmptyChatView: false,
    queuedMessageCount: 0,
  });

  return (
    <div data-testid="chat-main" style={chatMainStyle}>
      {isComposerDockVisible ? <div data-height={dockHeight} ref={dockedComposerRef} /> : null}
    </div>
  );
}

function overlayHeight(): string {
  const main = container?.querySelector<HTMLElement>('[data-testid="chat-main"]');
  return main?.style.getPropertyValue("--chatapp-composer-overlay-height") || "";
}
