// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { EventManager } from "./event-manager";

vi.mock("./calendar-header", () => ({ Header: () => null }));
vi.mock("./calendar-filter-bar", () => ({ FilterBar: () => null }));
vi.mock("./calendar-board-views", () => ({
  CalendarBoardViews: ({ view }: { view: string }) => <output>{view}</output>,
}));

it("keeps the mobile agenda after default view state and event refreshes", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.spyOn(window, "matchMedia").mockReturnValue({
    matches: true,
  } as MediaQueryList);
  const host = document.createElement("div");
  const root = createRoot(host);
  try {
    await act(async () =>
      root.render(<EventManager viewState={{ mode: "default" }} />),
    );
    expect(host.querySelector("output")?.textContent).toBe("list");
    await act(async () =>
      root.render(<EventManager events={[]} viewState={{ mode: "default" }} />),
    );
    expect(host.querySelector("output")?.textContent).toBe("list");
    await act(async () =>
      root.render(
        <EventManager
          events={[]}
          viewState={{ mode: "custom", entity_ids: ["event"] }}
        />,
      ),
    );
    expect(host.querySelector("output")?.textContent).toBe("list");
    const startTime = new Date("2026-10-09T09:30:00Z");
    await act(async () =>
      root.render(
        <EventManager
          events={[
            {
              id: "event",
              title: "Fixture",
              startTime,
              endTime: new Date("2026-10-09T10:30:00Z"),
              color: "blue",
            },
          ]}
          viewState={{ mode: "custom", entity_ids: ["event"] }}
        />,
      ),
    );
    expect(host.querySelector("output")?.textContent).toBe("day");
  } finally {
    act(() => root.unmount());
    vi.restoreAllMocks();
  }
});
