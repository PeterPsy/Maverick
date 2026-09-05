// @vitest-environment happy-dom
import { act, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { ChatExecutionMode } from "./ChatExecutionMode";

vi.mock("../lib/localRuntime", () => ({ requestLocalRuntime: vi.fn(async () => ({ available: true })) }));
vi.mock("./LocalMacChat", () => ({ LocalMacChat: () => <section>local-only</section> }));

it("unmounts server controllers and upload listeners when entering local mode", async () => {
  const cleanup = vi.fn();
  function Server() {
    useEffect(() => cleanup, []);
    return <section>server-only</section>;
  }
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => { root.render(<ChatExecutionMode><Server /></ChatExecutionMode>); });
    expect(host.textContent).toContain("server-only");
    const local = Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "Su questo Mac")!;
    await act(async () => { local.click(); });
    expect(cleanup).toHaveBeenCalledOnce();
    expect(host.textContent).toContain("local-only");
    expect(host.textContent).not.toContain("server-only");
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
