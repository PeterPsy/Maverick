import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { contact, state, task, work } from "../testFixtures";
import { WorkPanel } from "./WorkPanel";
import { ContactPanel } from "./ContactPanel";
import { TaskPanel } from "./TaskPanel";
import { TaskList } from "./TaskList";
import { TodayView } from "./TodayView";
import { WorksView } from "./WorksView";

const noop = async () => {};
const workProps = {
  contacts: [contact],
  tasks: [],
  activity: [],
  saving: false,
  preset: {},
  onClose: vi.fn(),
  onSave: noop,
  onIntegrate: noop,
  onAddDeliverable: noop,
  onUpdateDeliverable: noop,
  onNote: noop,
  onNewTask: vi.fn(),
  onToggleTask: noop,
  onEditTask: vi.fn(),
};

describe("record flows", () => {
  it("retains work edits after an unrelated record refresh and a failed save", async () => {
    const save = vi.fn().mockRejectedValue(new Error("Connessione interrotta"));
    const close = vi.fn();
    const { rerender } = render(
      <WorkPanel {...workProps} item={work} onClose={close} onSave={save} />,
    );
    fireEvent.change(screen.getByLabelText("Prossima azione"), {
      target: { value: "Inviare il brief aggiornato" },
    });
    rerender(
      <WorkPanel
        {...workProps}
        item={{ ...work, updated_at: "2026-09-30T09:00:00Z" }}
        onClose={close}
        onSave={save}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Salva lavoro" }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(
      (screen.getByLabelText("Prossima azione") as HTMLInputElement).value,
    ).toBe("Inviare il brief aggiornato");
    expect(close).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toContain(
      "Connessione interrotta",
    );
  });
  it("fills partner details when selecting a contact", () => {
    render(<WorkPanel {...workProps} item={null} />);
    fireEvent.change(screen.getByLabelText("Contatto collegato"), {
      target: { value: contact.id },
    });
    expect((screen.getByLabelText("Partner") as HTMLInputElement).value).toBe(
      "Outdoor",
    );
    expect(
      (screen.getByLabelText("Email partner") as HTMLInputElement).value,
    ).toBe(contact.email);
  });
  it("saves contact tags and archiving without dropping relationships", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(
      <ContactPanel
        activity={[]}
        contacts={[contact]}
        item={contact}
        onClose={vi.fn()}
        onEditTask={vi.fn()}
        onNewTask={vi.fn()}
        onNewWork={vi.fn()}
        onNote={noop}
        onSave={save}
        onToggleTask={noop}
        onWork={vi.fn()}
        saving={false}
        tasks={[task]}
        works={[work]}
      />,
    );
    fireEvent.change(screen.getByLabelText("Tag, separati da virgole"), {
      target: { value: "Sport, Brand" },
    });
    fireEvent.click(screen.getByLabelText("Archivia contatto"));
    fireEvent.click(screen.getByRole("button", { name: "Salva contatto" }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(
        contact.id,
        expect.objectContaining({ archived: true, tags: ["Sport", "Brand"] }),
      ),
    );
  });
  it("links a task to the selected work and its contact", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(
      <TaskPanel
        contacts={[contact]}
        item={null}
        onClose={vi.fn()}
        onSave={save}
        preset={{}}
        saving={false}
        works={[work]}
      />,
    );
    fireEvent.change(screen.getByLabelText("Attività"), {
      target: { value: "Inviare il brief" },
    });
    fireEvent.change(screen.getByLabelText("Lavoro collegato"), {
      target: { value: work.id },
    });
    fireEvent.click(screen.getByRole("button", { name: "Salva attività" }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(
        null,
        expect.objectContaining({
          collaboration_id: work.id,
          contact_id: contact.id,
        }),
      ),
    );
  });
  it("completes and reopens follow-ups through the visible checkbox", async () => {
    const toggle = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(
      <TaskList
        contacts={[contact]}
        onEdit={vi.fn()}
        onToggle={toggle}
        saving={false}
        tasks={[task]}
        works={[work]}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Completa Richiamare Anna" }),
    );
    expect(toggle).toHaveBeenCalledWith(task);
    const done = { ...task, done: true };
    rerender(
      <TaskList
        contacts={[contact]}
        onEdit={vi.fn()}
        onToggle={toggle}
        saving={false}
        tasks={[done]}
        works={[work]}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Riapri Richiamare Anna" }),
    );
    expect(toggle).toHaveBeenLastCalledWith(done);
  });
  it("keeps overdue invoices visible even when the work is closed", () => {
    render(
      <TodayView
        onCreate={vi.fn()}
        onEditTask={vi.fn()}
        onNewTask={vi.fn()}
        onOpen={vi.fn()}
        onTasks={vi.fn()}
        onToggleTask={noop}
        onWorks={vi.fn()}
        saving={false}
        state={{
          ...state,
          tasks: [],
          collaborations: [
            { ...work, phase: "completed", payment_status: "overdue" },
          ],
        }}
      />,
    );
    expect(screen.getByText("Campagna neve")).toBeTruthy();
    expect(screen.getByText(/2[.,]?500\s*€/)).toBeTruthy();
  });
  it("offers a persistent phase change without requiring dragging", async () => {
    const move = vi.fn().mockResolvedValue(undefined);
    render(
      <WorksView
        items={[work]}
        onCreate={vi.fn()}
        onMove={move}
        onOpen={vi.fn()}
        query=""
        saving={false}
      />,
    );
    fireEvent.change(screen.getByLabelText("Fase di Campagna neve"), {
      target: { value: "approval" },
    });
    expect(move).toHaveBeenCalledWith(work.id, "approval", "", "production");
    fireEvent.click(screen.getByRole("button", { name: "Elenco" }));
    expect(screen.queryByLabelText("Fase di Campagna neve")).toBeNull();
    expect(screen.getByText("Campagna neve")).toBeTruthy();
  });
});
