import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { state } from "./testFixtures";
import { useMartaOps } from "./useMartaOps";

const socket = vi.hoisted(() => ({
  onMessage: (_message: unknown) => {},
}));

vi.mock("@loopino/pwa-cache", () => ({
  connectAppEventSocket: (onMessage: (message: unknown) => void) => {
    socket.onMessage = onMessage;
    return () => {};
  },
  readLoopinoAppFrameContext: () => null,
  isExactLoopinoParentMessage: () => false,
}));

it("ignores an older bootstrap response after a successful mutation", async () => {
  let resolveBootstrap!: (response: Response) => void;
  const oldResponse = new Promise<Response>((resolve) => {
    resolveBootstrap = resolve;
  });
  const updated = {
    ...state,
    contacts: [{ ...state.contacts[0], name: "Anna aggiornata" }],
  };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_url, init) => {
    const request = JSON.parse(String(init?.body));
    if (request.action === "bootstrap") return oldResponse;
    return new Response(JSON.stringify({ state: updated }), { status: 200 });
  });
  const { result } = renderHook(() => useMartaOps());
  await act(async () => {
    await result.current.mutate({ action: "update_contact" });
  });
  await act(async () => {
    resolveBootstrap(new Response(JSON.stringify({ state }), { status: 200 }));
  });
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.state.contacts[0].name).toBe("Anna aggiornata");
});

it("refreshes a data event received while a local save is pending", async () => {
  let resolveSave!: (response: Response) => void;
  const saveResponse = new Promise<Response>((resolve) => {
    resolveSave = resolve;
  });
  const latest = {
    ...state,
    contacts: [
      { ...state.contacts[0], name: "Aggiornamento da un altro utente" },
    ],
  };
  let reads = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_url, init) => {
    const request = JSON.parse(String(init?.body));
    if (request.action !== "bootstrap") return saveResponse;
    reads += 1;
    return new Response(
      JSON.stringify({ state: reads === 1 ? state : latest }),
      {
        status: 200,
      },
    );
  });
  const { result } = renderHook(() => useMartaOps());
  await waitFor(() => expect(result.current.loading).toBe(false));
  let saving!: Promise<unknown>;
  act(() => {
    saving = result.current.mutate({ action: "update_contact" });
    socket.onMessage({
      type: "loopino.app.data-changed",
      owner_app_id: "marta-ops",
      resource: "state",
    });
  });
  expect(reads).toBe(1);
  await act(async () => {
    resolveSave(new Response(JSON.stringify({ state }), { status: 200 }));
    await saving;
  });
  await waitFor(() =>
    expect(result.current.state.contacts[0].name).toBe(
      "Aggiornamento da un altro utente",
    ),
  );
  expect(reads).toBe(2);
});
