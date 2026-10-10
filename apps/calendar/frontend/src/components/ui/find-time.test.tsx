// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { FindTime } from "./find-time";
import { findFreeTime } from "@/api";
import type { Event } from "./calendar-types";
vi.mock("@/api", () => ({
  findFreeTime: vi.fn(),
  checkAvailability: vi.fn(async () => ({ conflicts: [] })),
}));
vi.mock("@maverick/pwa-cache", () => ({
  maverickAppIsVisible: () => true,
  observeMaverickVisibility: () => () => {},
}));
(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});
const draft: Event = {
  id: "e",
  title: "Event",
  color: "blue",
  timezone: "Europe/Rome",
  startTime: new Date("2026-10-12T07:30Z"),
  endTime: new Date("2026-10-12T09:00Z"),
};
it("invalidates proposals and late responses when duration or invitees change", async () => {
  const host = document.createElement("div"),
    root = createRoot(host),
    select = vi.fn();
  let finish!: (result: {
    slots: Array<{ startTime: string; endTime: string }>;
  }) => void;
  vi.mocked(findFreeTime).mockReturnValueOnce(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  try {
    await act(async () =>
      root.render(
        <FindTime appId="calendar" draft={draft} onSelect={select} />,
      ),
    );
    act(() => host.querySelector("button")!.click());
    await act(async () =>
      root.render(
        <FindTime
          appId="calendar"
          draft={{ ...draft, attendees: ["new@example.com"] }}
          onSelect={select}
        />,
      ),
    );
    await act(async () =>
      finish({
        slots: [
          { startTime: "2026-10-13T08:00Z", endTime: "2026-10-13T09:00Z" },
        ],
      }),
    );
    expect(host.querySelector(".calendar-slot-choice")).toBeNull();
    vi.mocked(findFreeTime).mockResolvedValueOnce({
      slots: [{ startTime: "2026-10-13T08:00Z", endTime: "2026-10-13T09:30Z" }],
    });
    await act(async () => host.querySelector("button")!.click());
    expect(host.querySelector(".calendar-slot-choice")?.textContent).toContain(
      "10:00",
    );
    await act(async () =>
      root.render(
        <FindTime
          appId="calendar"
          draft={{ ...draft, endTime: new Date("2026-10-12T10:00Z") }}
          onSelect={select}
        />,
      ),
    );
    expect(host.querySelector(".calendar-slot-choice")).toBeNull();
  } finally {
    act(() => root.unmount());
  }
});
it("whole-day searches send civil-day duration and offer no controls for read-only events", async () => {
  const host = document.createElement("div"),
    root = createRoot(host);
  vi.mocked(findFreeTime).mockResolvedValue({ slots: [] });
  const allDay = {
    ...draft,
    all_day: true,
    startTime: new Date("2026-03-28T23:00Z"),
    endTime: new Date("2026-03-29T22:00Z"),
  };
  try {
    await act(async () =>
      root.render(
        <FindTime appId="calendar" draft={allDay} onSelect={vi.fn()} />,
      ),
    );
    await act(async () => host.querySelector("button")!.click());
    expect(findFreeTime).toHaveBeenCalledWith(
      "calendar",
      expect.objectContaining({
        all_day: true,
        duration_days: 1,
        timezone: "Europe/Rome",
      }),
      expect.any(AbortSignal),
    );
    await act(async () =>
      root.render(
        <FindTime appId="calendar" draft={draft} onSelect={vi.fn()} readOnly />,
      ),
    );
    expect(host.querySelector("button")).toBeNull();
  } finally {
    act(() => root.unmount());
  }
});
