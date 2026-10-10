// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppNotifications } from "./AppNotifications";
import type { AppRegistryItem } from "../api";

const transport = vi.hoisted(() => ({
  visible: true,
  event: (_event: object) => {},
  reconnect: () => {},
  visibility: (_visible: boolean) => {},
}));
vi.mock("@maverick/pwa-cache", () => ({
  maverickAppIsVisible: () => transport.visible,
  observeMaverickVisibility: (callback: typeof transport.visibility) => {
    transport.visibility = callback;
    callback(transport.visible);
    return () => {};
  },
  connectAppEventSocket: (
    callback: typeof transport.event,
    reconnect: typeof transport.reconnect,
  ) => {
    transport.event = callback;
    transport.reconnect = reconnect;
    return () => {};
  },
}));
vi.mock("../shellAuthorization", () => ({
  reportShellAuthorizationFailure: vi.fn(),
  shellAuthorizationEpoch: () => 1,
}));

const provider = {
  app_id: "calendar",
  name: "Calendar",
  status: "enabled",
  provides: [
    { interface: "notifications.inbox", version: "1", surfaces: ["backend"] },
  ],
} as AppRegistryItem;
const scope = { sessionGeneration: "alice-default", workspaceId: "default" };
const renderInbox = (notifications: ReactNode) => notifications;
const notice = {
  id: "reminder",
  title: "Dentista",
  scheduled_at: "2026-10-09T10:00:00Z",
  timezone: "Europe/Rome",
  open_params: { event_id: "appointment" },
};
let root: Root;
let host: HTMLDivElement;
const reply = (notifications = [notice], total = notifications.length) =>
  new Response(JSON.stringify({ notifications, total }));
const flush = async () =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(100);
  });
const click = async (text: string) =>
  act(async () => {
    const button = Array.from(host.querySelectorAll("button")).find((button) =>
      button.textContent?.includes(text),
    );
    expect(button).toBeDefined();
    button!.click();
  });

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.useFakeTimers();
  vi.spyOn(window, "matchMedia").mockReturnValue({
    matches: true,
    addEventListener: () => {},
    removeEventListener: () => {},
  } as unknown as MediaQueryList);
  // happy-dom lacks the native top-layer API; real behavior is covered by Chromium.
  Object.defineProperties(HTMLElement.prototype, {
    showPopover: { configurable: true, value: vi.fn() },
    hidePopover: { configurable: true, value: vi.fn() },
  });
  transport.visible = true;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(HTMLElement.prototype, "showPopover");
  Reflect.deleteProperty(HTMLElement.prototype, "hidePopover");
});

describe("App notification inbox", () => {
  it("withdraws a disabled provider immediately before the next refresh", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => reply()),
    );
    await act(async () =>
      root.render(
        <AppNotifications
          apps={[provider]}
          scope={scope}
          onOpenApp={() => {}}
          children={renderInbox}
          placement="sidebar"
        />,
      ),
    );
    await flush();
    await click("Notifiche");
    expect(host.textContent).toContain("Dentista");
    await act(async () =>
      root.render(
        <AppNotifications
          apps={[{ ...provider, status: "disabled" }]}
          scope={scope}
          onOpenApp={() => {}}
          children={renderInbox}
          placement="sidebar"
        />,
      ),
    );
    expect(host.textContent).not.toContain("Dentista");
    expect(host.querySelector(".bs-notifications__badge")).toBeNull();
  });

  it("keeps the central bell available when no app produces notifications", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await act(async () =>
      root.render(
        <AppNotifications
          apps={[]}
          scope={scope}
          onOpenApp={() => {}}
          children={renderInbox}
          placement="header"
        />,
      ),
    );
    await flush();
    await click("Notifiche");
    expect(host.textContent).toContain("Nessuna notifica");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("merges arbitrary enabled providers by time, namespaces ids and uses registry identity", async () => {
    const other = {
      ...provider,
      app_id: "jobs",
      name: "Jobs",
      logo: { kind: "image", value: "/apps/jobs/icon.png" },
    } as AppRegistryItem;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async (url: string) =>
          new Response(
            JSON.stringify({
              notifications: [
                {
                  ...notice,
                  created_at: url.includes("jobs")
                    ? "2026-10-10T11:00:00Z"
                    : "2026-10-10T10:00:00Z",
                  title: url.includes("jobs") ? "Export pronto" : "Dentista",
                  presentation: {
                    kind: "payment",
                    amount: "invalid",
                    app: "Wrong app",
                  },
                },
              ],
              total: 1,
            }),
          ),
      ),
    );
    await act(async () =>
      root.render(
        <AppNotifications
          apps={[
            provider,
            other,
            { ...other, app_id: "disabled", status: "disabled" },
          ]}
          scope={scope}
          onOpenApp={() => {}}
          children={renderInbox}
          placement="sidebar"
        />,
      ),
    );
    await flush();
    await click("Notifiche");
    const rows = host.querySelectorAll<HTMLElement>("[data-notification]");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("Export pronto");
    expect(rows[0].dataset.notification).not.toEqual(
      rows[1].dataset.notification,
    );
    expect(rows[0].dataset.kind).toBe("generic");
    expect(rows[0].querySelector("img")?.getAttribute("src")).toBe(
      "/apps/jobs/icon.png",
    );
    expect(host.textContent).not.toContain("Wrong app");
  });

  it("persists read-all only with supported capabilities and reflects same-id receipt updates", async () => {
    let read = false;
    const fetchMock = vi.fn(async (_url: string, options: RequestInit) => {
      const body = JSON.parse(String(options.body));
      if (body.action === "notifications.read") {
        expect(body).toMatchObject({ all: true });
        expect(body.id).toBeUndefined();
        read = true;
        return new Response("{}");
      }
      return new Response(
        JSON.stringify({
          notifications: [{ ...notice, read }],
          total: 1,
          unread_total: read ? 0 : 1,
          capabilities: { read: true },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const apps = [provider];
    await act(async () =>
      root.render(
        <AppNotifications
          apps={apps}
          scope={scope}
          onOpenApp={() => {}}
          children={renderInbox}
          placement="sidebar"
        />,
      ),
    );
    await flush();
    await click("Notifiche");
    expect(host.querySelector("[data-unread]")).not.toBeNull();
    await click("Segna lette");
    await flush();
    expect(
      host.querySelector("[data-notification]")?.hasAttribute("data-read"),
    ).toBe(true);
    expect(host.textContent).toContain("Dentista");
    expect(host.querySelector(".bs-notifications__badge")).toBeNull();
    read = false;
    transport.reconnect();
    await flush();
    expect(
      host.querySelector("[data-notification]")?.hasAttribute("data-read"),
    ).toBe(false);
  });

  it("dispatches advertised actions to their provider and never reports completion after failure", async () => {
    let fail = true,
      done = false;
    const fetchMock = vi.fn(async (_url: string, options: RequestInit) => {
      const body = JSON.parse(String(options.body));
      if (body.action === "notifications.action") {
        expect(body).toMatchObject({ id: "reminder", action_id: "accept" });
        if (fail) return new Response("{}", { status: 503 });
        done = true;
        return new Response(
          JSON.stringify({
            notification: { ...notice, action_done: "Accettato", read: true },
          }),
        );
      }
      return new Response(
        JSON.stringify({
          notifications: [
            {
              ...notice,
              action_done: done ? "Accettato" : undefined,
              read: done,
              actions: [{ id: "accept", label: "Accetta", done: "Accettato" }],
            },
          ],
          total: 1,
          unread_total: done ? 0 : 1,
          capabilities: { actions: true },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    await act(async () =>
      root.render(
        <AppNotifications
          apps={[provider]}
          scope={scope}
          onOpenApp={() => {}}
          children={renderInbox}
          placement="sidebar"
        />,
      ),
    );
    await flush();
    await click("Notifiche");
    await click("Accetta");
    expect(host.querySelector("[data-done]")).toBeNull();
    expect(host.querySelector("[data-action]")).not.toBeNull();
    expect(host.querySelector('[role="alert"]')).not.toBeNull();
    fail = false;
    await click("Accetta");
    await flush();
    expect(host.querySelector("[data-done]")?.textContent).toContain(
      "Accettato",
    );
    expect(host.querySelector("[data-action]")).toBeNull();
  });

  it("retains only failed cards when bulk dismissal partially fails", async () => {
    let removed = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, options: RequestInit) => {
        const body = JSON.parse(String(options.body));
        if (body.action === "notifications.dismiss") {
          if (body.id === "fail") return new Response("{}", { status: 503 });
          removed = true;
          return new Response("{}");
        }
        return reply(
          removed
            ? [{ ...notice, id: "fail", title: "Da riprovare" }]
            : [notice, { ...notice, id: "fail", title: "Da riprovare" }],
        );
      }),
    );
    await act(async () =>
      root.render(
        <AppNotifications
          apps={[provider]}
          scope={scope}
          onOpenApp={() => {}}
          children={renderInbox}
          placement="sidebar"
        />,
      ),
    );
    await flush();
    await click("Notifiche");
    await click("Chiudi visibili");
    await flush();
    expect(host.textContent).toContain("Da riprovare");
    expect(host.textContent).not.toContain("Dentista");
    expect(host.querySelector('[role="alert"]')).not.toBeNull();
  });

  it("retains one reader and unread state as the responsive surface moves or closes", async () => {
    const fetchMock = vi.fn(async () => reply());
    vi.stubGlobal("fetch", fetchMock);
    const apps = [provider];
    const renderAt = (visible: boolean, placement: "sidebar" | "header") =>
      act(async () =>
        root.render(
          <AppNotifications
            apps={apps}
            scope={scope}
            onOpenApp={() => {}}
            placement={placement}
          >
            {(notifications) =>
              visible ? (
                <div data-surface={placement} key={placement}>
                  {notifications}
                </div>
              ) : null
            }
          </AppNotifications>,
        ),
      );
    await renderAt(true, "sidebar");
    await flush();
    const sidebar = host.querySelector('[data-surface="sidebar"]')!;
    expect(sidebar.textContent).toContain("Notifiche (1)");
    await renderAt(true, "header");
    await flush();
    const header = host.querySelector('[data-surface="header"]')!;
    expect(sidebar.isConnected).toBe(false);
    expect(host.querySelectorAll(".bs-notifications__toggle")).toHaveLength(1);
    expect(header.textContent).toContain("Notifiche (1)");
    expect(
      header.querySelector(".bs-mobile-shell-header__button"),
    ).not.toBeNull();
    await renderAt(false, "sidebar");
    await flush();
    expect(host.querySelector("button")).toBeNull();
    await renderAt(true, "sidebar");
    await flush();
    expect(
      host.querySelector('[data-surface="sidebar"]')!.textContent,
    ).toContain("Notifiche (1)");
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("shows reminders without a Calendar frame and navigates through provider parameters", async () => {
    const fetchMock = vi.fn(async (_url: string, _options: RequestInit) =>
      reply(),
    );
    vi.stubGlobal("fetch", fetchMock);
    const open = vi.fn();
    await act(async () =>
      root.render(
        <AppNotifications
          apps={[provider]}
          scope={scope}
          onOpenApp={open}
          children={renderInbox}
          placement="sidebar"
        />,
      ),
    );
    await flush();
    expect(host.textContent).toContain("Notifiche (1)");
    expect(host.querySelector("iframe")).toBeNull();
    await click("Notifiche");
    expect(host.textContent).toContain("Dentista");
    const toggle = host.querySelector<HTMLButtonElement>(
      ".bs-notifications__toggle",
    )!;
    act(() =>
      host
        .querySelector(".bs-notifications__inbox")!
        .dispatchEvent(
          new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
        ),
    );
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(toggle);
    await click("Notifiche");
    await click("Dentista");
    expect(open).toHaveBeenCalledWith("calendar", { event_id: "appointment" });
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
      _app_secret_request: { required: false, logical_names: [] },
    });
  });

  it("coalesces notification events and reloads persisted alerts on reconnect", async () => {
    const fetchMock = vi.fn(async () => reply());
    vi.stubGlobal("fetch", fetchMock);
    await act(async () =>
      root.render(
        <AppNotifications
          children={renderInbox}
          placement="sidebar"
          apps={[provider]}
          scope={scope}
          onOpenApp={() => {}}
        />,
      ),
    );
    await flush();
    transport.event({
      type: "maverick.app.data-changed",
      owner_app_id: "calendar",
      resource: "notifications",
      workspace_id: "other",
    });
    await flush();
    expect(fetchMock).toHaveBeenCalledOnce();
    for (let i = 0; i < 3; i++)
      transport.event({
        type: "maverick.app.data-changed",
        owner_app_id: "calendar",
        resource: "notifications",
        workspace_id: "default",
      });
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    transport.reconnect();
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("persists acknowledgements and keeps the alert on save failure", async () => {
    let dismissed = false;
    let fail = true;
    const fetchMock = vi.fn(async (_url: string, options: RequestInit) => {
      const body = JSON.parse(String(options.body));
      if (body.action === "notifications.dismiss") {
        if (fail) return new Response("{}", { status: 503 });
        dismissed = true;
        return new Response("{}");
      }
      return reply(dismissed ? [] : [notice]);
    });
    vi.stubGlobal("fetch", fetchMock);
    await act(async () =>
      root.render(
        <AppNotifications
          children={renderInbox}
          placement="sidebar"
          apps={[provider]}
          scope={scope}
          onOpenApp={() => {}}
        />,
      ),
    );
    await flush();
    await click("Notifiche");
    await click("Chiudi");
    expect(host.textContent).toContain("Dentista");
    expect(host.querySelector('[role="alert"]')).not.toBeNull();
    fail = false;
    await click("Chiudi");
    await flush();
    expect(host.textContent).not.toContain("Dentista");
    expect(
      fetchMock.mock.calls.find(
        (call) =>
          JSON.parse(String(call[1].body)).action === "notifications.dismiss",
      )![1].credentials,
    ).toBe("same-origin");
  });

  it("aborts hidden reads, ignores late replies and drops inbox on workspace change", async () => {
    let resolve!: (response: Response) => void;
    let signal!: AbortSignal;
    const fetchMock = vi.fn((_url: string, options: RequestInit) => {
      signal = options.signal!;
      return new Promise<Response>((done) => {
        resolve = done;
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    await act(async () =>
      root.render(
        <AppNotifications
          children={renderInbox}
          placement="sidebar"
          key="alice"
          apps={[provider]}
          scope={scope}
          onOpenApp={() => {}}
        />,
      ),
    );
    await flush();
    transport.visible = false;
    transport.visibility(false);
    expect(signal.aborted).toBe(true);
    await act(async () => {
      resolve(reply());
    });
    expect(host.textContent).not.toContain("(1)");
    fetchMock.mockImplementationOnce(async () => reply());
    transport.visible = true;
    transport.visibility(true);
    await flush();
    expect(host.textContent).toContain("(1)");
    transport.visible = false;
    await act(async () =>
      root.render(
        <AppNotifications
          children={renderInbox}
          placement="sidebar"
          key="bob"
          apps={[provider]}
          scope={{
            ...scope,
            sessionGeneration: "bob-other",
            workspaceId: "other",
          }}
          onOpenApp={() => {}}
        />,
      ),
    );
    expect(host.textContent).not.toContain("(1)");
  });

  it("loads beyond the first 100 alerts when requested", async () => {
    const fetchMock = vi.fn(async (_url: string, options: RequestInit) => {
      const body = JSON.parse(String(options.body));
      return body.offset
        ? reply([{ ...notice, id: "old", title: "Avviso precedente" }], 101)
        : reply(
            Array.from({ length: 100 }, (_, i) => ({ ...notice, id: `n${i}` })),
            101,
          );
    });
    vi.stubGlobal("fetch", fetchMock);
    await act(async () =>
      root.render(
        <AppNotifications
          children={renderInbox}
          placement="sidebar"
          apps={[provider]}
          scope={scope}
          onOpenApp={() => {}}
        />,
      ),
    );
    await flush();
    await click("Notifiche");
    for (let i = 0; i < 20; i++) await click("Mostra altre");
    await flush();
    expect(host.textContent).toContain("Avviso precedente");
    expect(
      fetchMock.mock.calls.some(
        (call) => JSON.parse(String(call[1].body)).offset === 100,
      ),
    ).toBe(true);
  }, 15000);
});
