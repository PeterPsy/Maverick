import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { state, work } from "../testFixtures";
import { WorkIntegrations } from "./WorkIntegrations";

describe("WorkIntegrations", () => {
  it("uses saved accounts and exposes only useful work actions", () => {
    const preference = vi.fn();
    const integrate = vi.fn();
    const pick = vi.fn();
    render(
      <WorkIntegrations
        busy=""
        canCalendar
        canMail
        item={work}
        onIntegrate={integrate}
        onOpenCalendar={vi.fn()}
        onOpenDocument={vi.fn()}
        onOpenMail={vi.fn()}
        onPickDocument={pick}
        onPreferenceChange={preference}
        onRefresh={vi.fn()}
        onUnlinkDocument={vi.fn()}
        options={state.integration_options}
        preferences={state.integration_preferences}
        saving={false}
      />,
    );

    expect(
      (screen.getByLabelText("Account Mail") as HTMLSelectElement).value,
    ).toBe("mail-1");
    expect(
      (screen.getByLabelText("Calendario Google") as HTMLSelectElement).value,
    ).toBe("cal-1::primary");
    fireEvent.click(screen.getByRole("button", { name: "Crea bozza" }));
    fireEvent.click(screen.getByRole("button", { name: "Crea evento" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Aggiungi da Storage" }),
    );
    expect(integrate).toHaveBeenNthCalledWith(1, "mail");
    expect(integrate).toHaveBeenNthCalledWith(2, "calendar");
    expect(pick).toHaveBeenCalledOnce();
  });
});
