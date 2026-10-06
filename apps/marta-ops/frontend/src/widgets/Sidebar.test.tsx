import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MartaOpsSidebar } from "./marta-ops-sidebar/Sidebar";
import { MartaOpsSidebarFooter } from "./marta-ops-sidebar-footer/SidebarFooter";

const backend = vi.hoisted(() => vi.fn());
const socket = vi.hoisted(() => ({
  onMessage: (_message: unknown) => {},
  reconnect: () => {},
}));
vi.mock("../api", () => ({ callBackend: backend }));
vi.mock("@maverick/pwa-cache", async (importActual) => ({
  ...(await importActual<object>()),
  connectAppEventSocket: (
    onMessage: typeof socket.onMessage,
    reconnect: () => void,
  ) => {
    socket.onMessage = onMessage;
    socket.reconnect = reconnect;
    return vi.fn();
  },
}));

const origin = "https://shell.example.test";
const summary = {
  overdue_deliveries: 2,
  approvals: 3,
  open_tasks: 4,
  receivables: 5,
  overdue_payments: 1,
};
type ShellWindow = Window & { __MAVERICK_PLATFORM_ORIGIN__?: string };
function shellMessage(data: unknown, eventOrigin = origin) {
  fireEvent(
    window,
    new MessageEvent("message", { data, origin: eventOrigin, source: window }),
  );
}
function context(
  params: Record<string, unknown>,
  widget = "marta-ops-sidebar",
  mobile = false,
) {
  shellMessage({
    type: "maverick.widget.context-changed",
    context: {
      owner_app_id: "marta-ops",
      widget_id: widget,
      content: {
        payload: { active_app_params: params, is_mobile_layout: mobile },
      },
    },
  });
}
beforeEach(() => {
  backend.mockReset().mockResolvedValue({ summary });
  (window as ShellWindow).__MAVERICK_PLATFORM_ORIGIN__ = origin;
});
afterEach(() => {
  delete (window as ShellWindow).__MAVERICK_PLATFORM_ORIGIN__;
  window.history.replaceState({}, "", "/");
});

it("shows bounded live counts, opens a quick filter and closes the mobile sidebar", async () => {
  const post = vi.spyOn(window, "postMessage");
  render(<MartaOpsSidebar />);
  await screen.findByLabelText("2 consegne in ritardo");
  expect(backend).toHaveBeenCalledWith(
    {
      action: "sidebar_summary",
      today: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
    },
    expect.any(AbortSignal),
  );
  context({ app_page: "contacts" }, "marta-ops-sidebar", true);
  fireEvent.click(screen.getByRole("button", { name: /Da approvare/ }));
  expect(post).toHaveBeenCalledWith(
    {
      type: "maverick.widget.open-app",
      app_id: "marta-ops",
      params: {
        app_page: "deliveries",
        delivery_filter: "approval",
        reset_filters: true,
      },
    },
    origin,
  );
  expect(post).toHaveBeenCalledWith(
    { type: "maverick.shell.sidebar.close" },
    origin,
  );
  backend.mockResolvedValue({ summary: { ...summary, open_tasks: 3 } });
  socket.onMessage({
    type: "maverick.app.data-changed",
    owner_app_id: "marta-ops",
    resource: "state",
  });
  await screen.findByLabelText("3 attività da fare");
});

it("keeps the current selection when mobile layout context repeats old route params", async () => {
  render(<MartaOpsSidebar />);
  context({ app_page: "deliveries", delivery_filter: "approval" });
  shellMessage({
    type: "maverick.app.selection-changed",
    owner_app_id: "marta-ops",
    selection: {
      app_page: "deliveries",
      delivery_filter: "open",
    },
  });
  context(
    { app_page: "deliveries", delivery_filter: "approval" },
    "marta-ops-sidebar",
    true,
  );
  expect(
    screen
      .getByRole("button", { name: /Da approvare/ })
      .getAttribute("aria-pressed"),
  ).toBe("false");
  shellMessage(
    {
      type: "maverick.app.selection-changed",
      owner_app_id: "marta-ops",
      selection: { app_page: "contacts" },
    },
    "https://foreign.test",
  );
  expect(
    screen
      .getByRole("button", { name: /Consegne/ })
      .getAttribute("aria-current"),
  ).toBe("page");
  await screen.findByLabelText("2 consegne in ritardo");
});

it("recovers unavailable counts without presenting them as zero", async () => {
  backend.mockRejectedValueOnce(new Error("Unavailable"));
  render(<MartaOpsSidebar />);
  await screen.findByText("Contatori non disponibili.");
  expect(screen.queryByLabelText(/consegne in ritardo/)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Riprova" }));
  await screen.findByLabelText("2 consegne in ritardo");
  expect(screen.queryByText("Contatori non disponibili.")).toBeNull();
});

it("prefers live context over a late bootstrap response", async () => {
  window.history.replaceState({}, "", "/?context=opaque");
  let complete: (value: Response) => void = () => {};
  const fetch = vi.spyOn(window, "fetch").mockImplementation(
    () =>
      new Promise((resolve) => {
        complete = resolve;
      }) as Promise<Response>,
  );
  render(<MartaOpsSidebar />);
  context({ app_page: "tasks" });
  complete({
    ok: true,
    json: async () => ({
      context: {
        content: { payload: { active_app_params: { app_page: "today" } } },
      },
    }),
  } as Response);
  await waitFor(() =>
    expect(
      screen
        .getByRole("button", { name: /Attività/ })
        .getAttribute("aria-current"),
    ).toBe("page"),
  );
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("reports and retries context failures", async () => {
  window.history.replaceState({}, "", "/?context=opaque");
  vi.spyOn(window, "fetch")
    .mockResolvedValueOnce({ ok: false } as Response)
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        context: {
          content: { payload: { active_app_params: { app_page: "ideas" } } },
        },
      }),
    } as Response);
  render(<MartaOpsSidebar />);
  await screen.findByText("Contesto sidebar non disponibile.");
  fireEvent.click(screen.getByRole("button", { name: "Riprova" }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Idee" }).getAttribute("aria-current"),
    ).toBe("page"),
  );
});

it("uses the current footer action for clicks and trusted mobile header invokes", async () => {
  const post = vi.spyOn(window, "postMessage");
  render(<MartaOpsSidebarFooter />);
  context({ app_page: "contacts" }, "marta-ops-sidebar-footer");
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "Nuovo contatto",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  const invoke = {
    type: "maverick.widget.primary-action.invoke",
    owner_app_id: "marta-ops",
    widget_id: "marta-ops-sidebar-footer",
  };
  post.mockClear();
  shellMessage(invoke, "https://foreign.test");
  shellMessage({ ...invoke, widget_id: "another-footer" });
  expect(post).not.toHaveBeenCalled();
  shellMessage(invoke);
  expect(post).toHaveBeenCalledWith(
    {
      type: "maverick.widget.open-app",
      app_id: "marta-ops",
      params: {
        app_page: "contacts",
        new_contact: true,
        new_contact_request_id: expect.any(String),
      },
    },
    origin,
  );
  context({ app_page: "ideas" }, "marta-ops-sidebar-footer");
  fireEvent.click(screen.getByRole("button", { name: "Nuova idea" }));
  expect(post).toHaveBeenLastCalledWith(
    {
      type: "maverick.widget.open-app",
      app_id: "marta-ops",
      params: {
        app_page: "ideas",
        new_idea: true,
        new_idea_request_id: expect.any(String),
      },
    },
    origin,
  );
});
