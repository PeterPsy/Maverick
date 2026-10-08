/**
 * @vitest-environment happy-dom
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  externalHttpUrlFromMessage,
  externalUrlDispositionFromMessage,
  openExternalUrl,
} from "./externalUrl";

describe("external URL broker", () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
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

  it("keeps installed-app OAuth in the current browser container", async () => {
    const assign = vi.fn();
    const open = vi.fn();

    await openExternalUrl("https://accounts.google.com/oauth", "same-window", { assign, open });

    expect(assign).toHaveBeenCalledWith("https://accounts.google.com/oauth");
    expect(open).not.toHaveBeenCalled();
  });

  it("retains popup behavior and a same-window fallback for normal browser use", async () => {
    const assign = vi.fn();
    const open = vi.fn(() => null);

    await openExternalUrl("https://example.com", "new-window", { assign, open });

    expect(open).toHaveBeenCalledWith("https://example.com", "_blank", "noopener,noreferrer");
    expect(assign).toHaveBeenCalledWith("https://example.com");
  });

  it("uses top-level navigation for links opened from an installed web app", async () => {
    const assign = vi.fn();
    const open = vi.fn();

    await openExternalUrl("https://example.com", "new-window", { assign, open, standalone: true });

    expect(assign).toHaveBeenCalledWith("https://example.com");
    expect(open).not.toHaveBeenCalled();
  });

  it("uses the native macOS opener before browser and standalone effects", async () => {
    const assign = vi.fn();
    const open = vi.fn();
    const nativeOpen = vi.fn(async () => {});
    await openExternalUrl("https://accounts.google.com/oauth", "same-window", {
      assign, open, nativeOpen, standalone: true,
    });
    expect(nativeOpen).toHaveBeenCalledExactlyOnceWith("https://accounts.google.com/oauth");
    expect(open).not.toHaveBeenCalled();
    expect(assign).not.toHaveBeenCalled();
  });

  it("discovers the installed native handler and requests one external launch", async () => {
    const postMessage = vi.fn(async () => true);
    vi.stubGlobal("webkit", { messageHandlers: { maverickExternalURL: { postMessage } } });
    const open = vi.spyOn(window, "open");
    const assign = vi.spyOn(window.location, "assign");
    await openExternalUrl("https://example.com/article");
    expect(postMessage).toHaveBeenCalledExactlyOnceWith({ url: "https://example.com/article" });
    expect(open).not.toHaveBeenCalled();
    expect(assign).not.toHaveBeenCalled();
  });

  it("falls back through ordinary navigation if the native request fails", async () => {
    const assign = vi.fn();
    const open = vi.fn(() => null);
    const nativeOpen = vi.fn(async () => { throw new Error("native unavailable"); });
    await openExternalUrl("https://example.com", "new-window", { assign, open, nativeOpen });
    expect(open).toHaveBeenCalledTimes(1);
    expect(assign).toHaveBeenCalledExactlyOnceWith("https://example.com");
  });
});
