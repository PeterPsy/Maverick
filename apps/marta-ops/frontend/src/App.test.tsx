import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { state, work } from "./testFixtures";
import { App } from "./App";

const mutation = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
const integration = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));

vi.mock("./useMartaOps", () => ({
  useMartaOps: () => ({
    state,
    loading: false,
    saving: false,
    error: "",
    clearError: vi.fn(),
    mutate: mutation,
    integrate: integration,
    refresh: vi.fn(),
  }),
}));

beforeEach(() => {
  mutation.mockClear();
  integration.mockClear();
});

afterEach(() => {
  state.collaborations = [work];
  delete (window as Window & { __MAVERICK_PLATFORM_ORIGIN__?: string })
    .__MAVERICK_PLATFORM_ORIGIN__;
});

function navigate(params: Record<string, unknown>) {
  fireEvent(
    window,
    new MessageEvent("message", {
      origin: window.location.origin,
      source: window,
      data: { type: "maverick.app.navigate", app_id: "marta-ops", params },
    }),
  );
}

it("keeps section search and filters while navigating and starts fresh on remount", () => {
  const app = render(<App />);
  navigate({ app_page: "work" });
  fireEvent.click(screen.getByRole("button", { name: "Elenco" }));
  fireEvent.change(screen.getByLabelText("Filtra per tipo"), {
    target: { value: "partnership" },
  });
  fireEvent.change(screen.getByLabelText("Cerca lavori"), {
    target: { value: "neve" },
  });
  navigate({ app_page: "tasks" });
  fireEvent.change(screen.getByLabelText("Cerca attività"), {
    target: { value: "Anna" },
  });
  navigate({ app_page: "work" });
  expect(
    (screen.getByLabelText("Cerca lavori") as HTMLInputElement).value,
  ).toBe("neve");
  expect(
    (screen.getByLabelText("Filtra per tipo") as HTMLSelectElement).value,
  ).toBe("partnership");
  expect(
    screen.getByRole("button", { name: "Elenco" }).getAttribute("aria-pressed"),
  ).toBe("true");
  navigate({ app_page: "tasks" });
  expect(
    (screen.getByLabelText("Cerca attività") as HTMLInputElement).value,
  ).toBe("Anna");
  app.unmount();
  render(<App />);
  navigate({ app_page: "work" });
  expect(
    (screen.getByLabelText("Cerca lavori") as HTMLInputElement).value,
  ).toBe("");
  expect(
    (screen.getByLabelText("Filtra per tipo") as HTMLSelectElement).value,
  ).toBe("");
});

it("applies quick filters, clears conflicting search and retains manual filter changes", () => {
  state.collaborations = [
    {
      ...work,
      deliverables: [
        {
          id: "d1",
          title: "Da approvare",
          status: "approval",
          due_date: "",
          created_at: "",
          updated_at: "",
        },
        {
          id: "d2",
          title: "In produzione",
          status: "in_progress",
          due_date: "",
          created_at: "",
          updated_at: "",
        },
      ],
    },
    {
      ...work,
      id: "w2",
      title: "Pagamento scaduto",
      phase: "completed",
      payment_status: "overdue",
    },
    { ...work, id: "w3", title: "Da fatturare", payment_status: "to_invoice" },
  ];
  render(<App />);
  navigate({ app_page: "deliveries" });
  fireEvent.change(screen.getByLabelText("Cerca consegne"), {
    target: { value: "invisibile" },
  });
  navigate({
    app_page: "deliveries",
    delivery_filter: "approval",
    reset_filters: true,
  });
  expect(
    (screen.getByLabelText("Cerca consegne") as HTMLInputElement).value,
  ).toBe("");
  expect(
    screen.getByRole("button", { name: "Apri Da approvare in Campagna neve" }),
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", {
      name: "Apri In produzione in Campagna neve",
    }),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Aperte" }));
  navigate({
    app_page: "admin",
    admin_filter: "receivables",
    reset_filters: true,
  });
  expect(
    screen.getByRole("button", { name: "Apri Pagamento scaduto" }),
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Apri Da fatturare" }),
  ).toBeNull();
  navigate({ app_page: "deliveries" });
  expect(
    screen.getByRole("button", { name: "Aperte" }).getAttribute("aria-pressed"),
  ).toBe("true");
});

it("focuses idea capture for a sidebar create request", () => {
  render(<App />);
  navigate({
    app_page: "ideas",
    new_idea: true,
    new_idea_request_id: "idea-1",
  });
  expect(document.activeElement).toBe(screen.getByLabelText("Titolo idea"));
});

it("uses the shell sidebar as navigation while keeping standalone section controls", () => {
  (
    window as Window & { __MAVERICK_PLATFORM_ORIGIN__?: string }
  ).__MAVERICK_PLATFORM_ORIGIN__ = window.location.origin;
  render(<App />);
  expect(screen.queryByRole("navigation", { name: "Sezioni" })).toBeNull();
  navigate({ app_page: "contacts" });
  expect(screen.getByLabelText("Nuovo contatto")).toBeTruthy();
});

it("preserves the contact draft while opening and closing a related task", async () => {
  render(<App />);
  fireEvent.click(
    within(screen.getAllByRole("navigation", { name: "Sezioni" })[0]).getByRole(
      "button",
      { name: "Contatti" },
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: /Anna Rossi Marketing/ }));
  fireEvent.change(screen.getByLabelText("Nome"), {
    target: { value: "Anna modificata" },
  });
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Attività",
    }),
  );
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Nuova attività",
    }),
  );
  expect(screen.getByRole("dialog").textContent).toContain("Il prossimo passo");
  await userEvent.keyboard("{Escape}");
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Dettagli",
    }),
  );
  expect((screen.getByLabelText("Nome") as HTMLInputElement).value).toBe(
    "Anna modificata",
  );
});

it("opens a sidebar create request once even when navigation is repeated", () => {
  render(<App />);
  const request = {
    type: "maverick.app.navigate",
    app_id: "marta-ops",
    params: {
      app_page: "contacts",
      new_contact: true,
      new_contact_request_id: "request-1",
    },
  };
  for (let i = 0; i < 2; i++)
    fireEvent(
      window,
      new MessageEvent("message", {
        data: request,
        origin: window.location.origin,
        source: window,
      }),
    );
  expect(screen.getAllByRole("dialog", { hidden: true })).toHaveLength(1);
  expect(screen.getByRole("button", { name: "Salva contatto" })).toBeTruthy();
});

it("saves the foreground task when two create requests open stacked drawers", async () => {
  render(<App />);
  for (const title of ["Prima attività", "Seconda attività"]) {
    fireEvent(
      window,
      new MessageEvent("message", {
        data: {
          type: "maverick.app.navigate",
          app_id: "marta-ops",
          params: { new_task: true, new_task_request_id: title },
        },
        origin: window.location.origin,
        source: window,
      }),
    );
    fireEvent.change(
      within(screen.getByRole("dialog")).getByLabelText("Attività"),
      {
        target: { value: title },
      },
    );
  }
  fireEvent.click(screen.getByRole("button", { name: "Salva attività" }));
  await waitFor(() =>
    expect(mutation).toHaveBeenLastCalledWith({
      action: "create_task",
      task: expect.objectContaining({ title: "Seconda attività" }),
    }),
  );
  expect((screen.getByLabelText("Attività") as HTMLInputElement).value).toBe(
    "Prima attività",
  );
});

it("validates a Storage picker return through the backend", async () => {
  render(<App />);
  fireEvent(
    window,
    new MessageEvent("message", {
      data: {
        type: "maverick.app.navigate",
        app_id: "marta-ops",
        params: {
          picker_mode: "workspace-file",
          picker_context: workId(),
          storage_picker_result: JSON.stringify({
            file: {
              workspace_relative_path: "storage/uploaded/brief.pdf",
            },
          }),
        },
      },
      origin: window.location.origin,
      source: window,
    }),
  );
  await waitFor(() =>
    expect(integration).toHaveBeenCalledWith({
      action: "link_storage_file",
      id: workId(),
      workspace_relative_path: "storage/uploaded/brief.pdf",
    }),
  );
});

function workId() {
  return state.collaborations[0].id;
}
