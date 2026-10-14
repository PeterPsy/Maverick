// @vitest-environment happy-dom
import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const googlePost = vi.hoisted(() => vi.fn());
vi.mock("../src/api", () => ({ googlePost }));

describe("System-browser Google landing", () => {
  let root: Root;
  let container: HTMLDivElement;
  beforeEach(() => {
    vi.resetModules();
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div"); document.body.append(container); root = createRoot(container);
    googlePost.mockResolvedValue({ authorization_url: "https://accounts.google.com/o/oauth2/v2/auth?state=state" });
  });
  afterEach(() => { act(() => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.resetAllMocks(); });

  it("removes fragment authority before rendering and launches only once in StrictMode", async () => {
    const state = "s".repeat(43), handoff = "h".repeat(64);
    window.location.href = `https://loopino.example/?google_handoff=1#${state}.${handoff}`;
    const replace = vi.spyOn(window.location, "replace").mockImplementation(() => {});
    const module = await import("../src/components/GoogleBrowserHandoff");
    expect(window.location.hash).toBe("");
    expect(window.location.search).toBe("?google_handoff=1");
    await act(async () => root.render(<StrictMode><module.GoogleBrowserHandoff /></StrictMode>));
    expect(googlePost).toHaveBeenCalledExactlyOnceWith("/api/auth/google/handoff", { state, handoff });
    expect(replace).toHaveBeenCalledExactlyOnceWith("https://accounts.google.com/o/oauth2/v2/auth?state=state");
    expect(container.textContent).not.toContain(handoff);
  });

  it("shows an expired handoff after reload instead of claiming that Google connected", async () => {
    window.location.href = "https://loopino.example/?google_handoff=1";
    const module = await import("../src/components/GoogleBrowserHandoff");
    await act(async () => root.render(<module.GoogleBrowserHandoff />));
    expect(container.textContent).toContain("Return to Loopino and try again");
    expect(container.textContent).not.toContain("Google connected");
    expect(googlePost).not.toHaveBeenCalled();
  });

  it("explains cancelled consent without opening Google again", async () => {
    window.location.href = "https://loopino.example/?google_handoff_done=1&google_error=google_consent_cancelled";
    const module = await import("../src/components/GoogleBrowserHandoff");
    await act(async () => root.render(<module.GoogleBrowserHandoff />));
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("cancelled");
    expect(window.location.search).toContain("google_consent_cancelled");
    expect(googlePost).not.toHaveBeenCalled();
  });
});
