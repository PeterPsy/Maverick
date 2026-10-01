import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { state, work } from "../testFixtures";
import type { Collaboration, Deliverable } from "../types";
import { AdministrationView } from "./AdministrationView";
import { DeliveriesView } from "./DeliveriesView";
import { WorkPanel } from "./WorkPanel";

const delivery: Deliverable = {
  id: "d1",
  title: "Reel principale",
  status: "approval",
  due_date: "2026-09-29",
  created_at: "2026-09-20T08:00:00Z",
  updated_at: "2026-09-20T08:00:00Z",
};

const workWithDelivery: Collaboration = {
  ...work,
  deliverables: [delivery],
};

describe("operational screens", () => {
  it("shows deliveries across works and updates their status", () => {
    const open = vi.fn();
    const update = vi.fn().mockResolvedValue(undefined);
    render(
      <DeliveriesView
        items={[workWithDelivery]}
        onOpen={open}
        onUpdate={update}
        query=""
        saving={false}
      />,
    );

    expect(screen.getByText("Reel principale")).toBeTruthy();
    expect(screen.getAllByText("Campagna neve")).toHaveLength(2);
    fireEvent.change(screen.getByLabelText("Stato di Reel principale"), {
      target: { value: "published" },
    });
    expect(update).toHaveBeenCalledWith(work.id, delivery.id, {
      status: "published",
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: "Apri Reel principale in Campagna neve",
      }),
    );
    expect(open).toHaveBeenCalledWith(workWithDelivery);
  });

  it("updates payment, contract and rights from administration", () => {
    const update = vi.fn().mockResolvedValue(undefined);
    render(
      <AdministrationView
        items={[{ ...work, contract_status: "draft" }]}
        onOpen={vi.fn()}
        onUpdate={update}
        query=""
        saving={false}
      />,
    );

    expect(screen.getAllByText(/2[.,]?500\s*€/)).toHaveLength(2);
    fireEvent.change(screen.getByLabelText("Pagamento di Campagna neve"), {
      target: { value: "overdue" },
    });
    expect(update).toHaveBeenCalledWith(work.id, {
      payment_status: "overdue",
    });
    fireEvent.change(screen.getByLabelText("Contratto di Campagna neve"), {
      target: { value: "signed" },
    });
    expect(update).toHaveBeenCalledWith(work.id, {
      contract_status: "signed",
    });
    fireEvent.change(
      screen.getByLabelText("Scadenza diritti di Campagna neve"),
      { target: { value: "2026-12-31" } },
    );
    expect(update).toHaveBeenCalledWith(work.id, {
      rights_expiry_date: "2026-12-31",
    });
  });

  it("opens a work directly on its deliveries tab", () => {
    render(
      <WorkPanel
        activity={[]}
        contacts={[]}
        initialTab="deliverables"
        item={workWithDelivery}
        onAddDeliverable={vi.fn()}
        onClose={vi.fn()}
        onEditTask={vi.fn()}
        integrationOptions={state.integration_options}
        integrationPreferences={state.integration_preferences}
        onIntegrate={vi.fn()}
        onOpenCalendar={vi.fn()}
        onOpenDocument={vi.fn()}
        onOpenMail={vi.fn()}
        onPickDocument={vi.fn()}
        onRefreshIntegrations={vi.fn()}
        onUnlinkDocument={vi.fn()}
        onUpdateIntegrationPreferences={vi.fn()}
        onNewTask={vi.fn()}
        onNote={vi.fn()}
        onSave={vi.fn()}
        onToggleTask={vi.fn()}
        onUpdateDeliverable={vi.fn()}
        preset={{}}
        saving={false}
        tasks={[]}
      />,
    );

    expect(screen.getByText("Reel principale")).toBeTruthy();
    expect(
      screen
        .getByRole("button", { name: "Consegne (1)" })
        .getAttribute("aria-pressed"),
    ).toBe("true");
  });
});
