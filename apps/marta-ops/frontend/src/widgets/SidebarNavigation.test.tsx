import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "../App";
import { SECTIONS } from "../navigation";
import { state, work } from "../testFixtures";
import { MartaOpsSidebar } from "./marta-ops-sidebar/Sidebar";
import { MartaOpsSidebarFooter } from "./marta-ops-sidebar-footer/SidebarFooter";

const integration = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
vi.mock("../useMartaOps", () => ({
  useMartaOps: () => ({
    state: {
      ...state,
      collaborations: [
        {
          ...work,
          deliverables: [
            { id: "d1", title: "Approvare", status: "approval", due_date: "" },
            {
              id: "d2",
              title: "Scaduta",
              status: "in_progress",
              due_date: "1900-01-01",
            },
          ],
        },
        {
          ...work,
          id: "w2",
          title: "Da fatturare",
          payment_status: "to_invoice",
        },
      ],
    },
    loading: false,
    saving: false,
    error: "",
    clearError: vi.fn(),
    mutate: vi.fn(),
    integrate: integration,
    refresh: vi.fn(),
  }),
}));
vi.mock("../api", () => ({
  callBackend: vi.fn().mockResolvedValue({
    summary: {
      overdue_deliveries: 1,
      approvals: 1,
      open_tasks: 1,
      receivables: 1,
      overdue_payments: 0,
    },
  }),
}));
vi.mock("@loopino/pwa-cache", async (importActual) => ({
  ...(await importActual<object>()),
  connectAppEventSocket: () => vi.fn(),
}));

const origin = "https://shell.example.test";
type ShellWindow = Window & { __LOOPINO_PLATFORM_ORIGIN__?: string };

beforeEach(() => {
  (window as ShellWindow).__LOOPINO_PLATFORM_ORIGIN__ = origin;
  // WidgetSlot only routes widget.open-app; AppFrameHost rejects app.open-app
  // from widget frames. Relay accepted widget requests into the real app.
  vi.spyOn(window, "postMessage").mockImplementation((message) => {
    const data =
      message.type === "loopino.widget.open-app"
        ? { ...message, type: "loopino.app.navigate" }
        : message.type === "loopino.app.selection-changed"
          ? message
          : null;
    if (data)
      window.dispatchEvent(
        new MessageEvent("message", { data, origin, source: window }),
      );
  });
});
afterEach(() => {
  delete (window as ShellWindow).__LOOPINO_PLATFORM_ORIGIN__;
});

async function mount() {
  const app = render(
    <>
      <App />
      <MartaOpsSidebar />
      <div data-testid="sidebar-footer">
        <MartaOpsSidebarFooter />
      </div>
    </>,
  );
  await screen.findByLabelText("1 consegne in ritardo");
  return {
    sections: within(
      screen.getByRole("navigation", { name: "Sezioni Marta Ops" }),
    ),
    filters: within(screen.getByRole("navigation", { name: "Filtri rapidi" })),
    footer: within(app.getByTestId("sidebar-footer")),
  };
}

it("changes the rendered app view for every sidebar section click", async () => {
  const { sections } = await mount();
  for (const section of [...SECTIONS.slice(1), SECTIONS[0]]) {
    const button = sections.getByRole("button", {
      name: new RegExp(`^${section.label}`),
    });
    fireEvent.click(button);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toMatch(
      new RegExp(`^${section.label}`),
    );
    expect(button.getAttribute("aria-current")).toBe("page");
  }
});

it("renders the requested delivery and payment records after quick-filter clicks", async () => {
  const { filters } = await mount();
  fireEvent.click(filters.getByRole("button", { name: /^In ritardo/ }));
  expect(
    screen.getByRole("button", { name: "Apri Scaduta in Campagna neve" }),
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Apri Approvare in Campagna neve" }),
  ).toBeNull();
  fireEvent.click(filters.getByRole("button", { name: /^Da approvare/ }));
  expect(
    screen.getByRole("button", { name: "Apri Approvare in Campagna neve" }),
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Apri Scaduta in Campagna neve" }),
  ).toBeNull();
  fireEvent.click(filters.getByRole("button", { name: /^Da incassare/ }));
  expect(
    screen.getByRole("button", { name: "Apri Campagna neve" }),
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Apri Da fatturare" }),
  ).toBeNull();
});

it.each([
  ["Lavori", "Nuovo lavoro", "Salva lavoro"],
  ["Contatti", "Nuovo contatto", "Salva contatto"],
  ["Attività", "Nuova attività", "Salva attività"],
  ["Idee", "Nuova idea", ""],
])(
  "opens the contextual footer action in %s",
  async (section, action, save) => {
    const { sections, footer } = await mount();
    fireEvent.click(
      sections.getByRole("button", { name: new RegExp(`^${section}`) }),
    );
    fireEvent.click(footer.getByRole("button", { name: action }));
    if (save)
      expect(
        within(screen.getByRole("dialog")).getByRole("button", { name: save }),
      ).toBeTruthy();
    else
      expect(document.activeElement).toBe(screen.getByLabelText("Titolo idea"));
  },
);
