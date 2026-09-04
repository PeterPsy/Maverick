/**
 * @vitest-environment happy-dom
 */
import { describe, expect, it, vi } from "vitest";
import {
  externalHttpUrlFromMessage,
  externalUrlDispositionFromMessage,
  openExternalUrl,
} from "./externalUrl";

describe("external URL broker", () => {
  it("accepts only HTTP(S) navigation targets", () => {
    expect(externalHttpUrlFromMessage("https://accounts.google.com/o/oauth2/auth")).toBe(
      "https://accounts.google.com/o/oauth2/auth",
    );
    expect(externalHttpUrlFromMessage("javascript:alert(1)")).toBeNull();
  });

  it("accepts same-window only as an explicit disposition", () => {
    expect(externalUrlDispositionFromMessage("same-window")).toBe("same-window");
    expect(externalUrlDispositionFromMessage("new-window")).toBe("new-window");
    expect(externalUrlDispositionFromMessage("same_window")).toBe("new-window");
  });

  it("keeps installed-app OAuth in the current browser container", () => {
    const assign = vi.fn();
    const open = vi.fn();

    openExternalUrl("https://accounts.google.com/oauth", "same-window", { assign, open });

    expect(assign).toHaveBeenCalledWith("https://accounts.google.com/oauth");
    expect(open).not.toHaveBeenCalled();
  });

  it("retains popup behavior and a same-window fallback for normal browser use", () => {
    const assign = vi.fn();
    const open = vi.fn(() => null);

    openExternalUrl("https://example.com", "new-window", { assign, open });

    expect(open).toHaveBeenCalledWith("https://example.com", "_blank", "noopener,noreferrer");
    expect(assign).toHaveBeenCalledWith("https://example.com");
  });
});
