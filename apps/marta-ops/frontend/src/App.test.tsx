import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { state } from "./testFixtures";
import { App } from "./App";

const mutation = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));

vi.mock("./useMartaOps", () => ({
  useMartaOps: () => ({
    state,
    loading: false,
    saving: false,
    error: "",
    clearError: vi.fn(),
    mutate: mutation,
    integrate: vi.fn(),
    refresh: vi.fn(),
  }),
}));

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
