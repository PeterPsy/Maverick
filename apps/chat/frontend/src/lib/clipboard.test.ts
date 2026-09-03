/**
 * @vitest-environment happy-dom
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { copyTextToClipboard } from "./clipboard";

const originalClipboard = navigator.clipboard;
const originalExecCommand = document.execCommand;

afterEach(() => {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: originalClipboard,
  });
  Object.defineProperty(document, "execCommand", {
    configurable: true,
    value: originalExecCommand,
  });
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

describe("copyTextToClipboard", () => {
  it("uses the async Clipboard API when the browser accepts the write", async () => {
    const writeText = vi.fn(async () => undefined);
    const execCommand = installExecCommand(() => true);
    installClipboard(writeText);

    await expect(copyTextToClipboard("Modern copy")).resolves.toBe(true);

    expect(writeText).toHaveBeenCalledWith("Modern copy");
    expect(execCommand).not.toHaveBeenCalled();
  });

  it("copies the selected text when an isolated frame is denied async clipboard access", async () => {
    const writeText = vi.fn(async () => {
      throw new DOMException("Write permission denied.", "NotAllowedError");
    });
    const focusTarget = document.createElement("button");
    document.body.append(focusTarget);
    focusTarget.focus();
    const execCommand = installExecCommand(() => {
      const textarea = document.querySelector<HTMLTextAreaElement>("textarea[readonly]");
      expect(textarea?.value).toBe("Fallback copy");
      expect(document.activeElement).toBe(textarea);
      expect(textarea?.selectionStart).toBe(0);
      expect(textarea?.selectionEnd).toBe("Fallback copy".length);
      return true;
    });
    installClipboard(writeText);

    await expect(copyTextToClipboard("Fallback copy")).resolves.toBe(true);

    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(document.querySelector("textarea[readonly]")).toBeNull();
    expect(document.activeElement).toBe(focusTarget);
  });

  it("does not report success when neither clipboard path writes the text", async () => {
    installClipboard(vi.fn(async () => {
      throw new DOMException("Write permission denied.", "NotAllowedError");
    }));
    installExecCommand(() => false);

    await expect(copyTextToClipboard("Uncopied text")).resolves.toBe(false);
  });
});

function installClipboard(writeText: (content: string) => Promise<void>) {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
}

function installExecCommand(implementation: (command: string) => boolean) {
  const execCommand = vi.fn(implementation);
  Object.defineProperty(document, "execCommand", {
    configurable: true,
    value: execCommand,
  });
  return execCommand;
}
