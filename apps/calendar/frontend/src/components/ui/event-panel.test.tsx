// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { EventPanel } from "./calendar-event-panel";
import { EventReminders } from "./event-reminders";
import { EventDescription } from "./event-description";
import type { Event } from "./calendar-types";
(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => localStorage.clear());
const event: Event = {
  id: "event",
  title: "Meeting",
  location: "Room 1",
  organizer: "owner@example.com",
  description: "Read https://example.com",
  startTime: new Date("2026-10-12T07:30:00Z"),
  endTime: new Date("2026-10-12T09:00:00Z"),
  timezone: "Europe/Rome",
  color: "blue",
  source: "google_calendar",
  attendees: ["guest@example.com"],
  attendee_details: [
    {
      email: "guest@example.com",
      displayName: "Guest name",
      responseStatus: "accepted",
    },
  ],
  external_refs: {
    provider: "google",
    provider_event_id: "remote",
    calendar_connection_id: "connection",
    provider_calendar_id: "primary",
    provider_calendar_access_role: "owner",
    provider_calendar_summary: "Work",
    htmlLink: "https://calendar.google.com/event",
  },
};
const props = {
  mode: "details" as const,
  draft: event,
  error: "",
  isSaving: false,
  canSave: true,
  categories: [],
  colors: [],
  availableTags: [],
  getColorClasses: () => ({ bg: "", text: "" }),
  setDraft: vi.fn(),
  toggleTag: vi.fn(),
  onCreate: vi.fn(),
  onUpdate: vi.fn(),
  onDelete: vi.fn(),
  onClose: vi.fn(),
};
it("opens a readable event with location, invitee response and provider link before edit", async () => {
  const host = document.createElement("div"),
    root = createRoot(host);
  try {
    await act(async () =>
      root.render(<EventPanel {...props} hasChanges={false} />),
    );
    expect(host.querySelector("input")).toBeNull();
    expect(host.textContent).toContain("Room 1");
    expect(host.textContent).toContain("Guest name");
    expect(host.textContent).toContain("Accepted");
    expect(
      host.querySelector('a[href="https://calendar.google.com/event"]'),
    ).not.toBeNull();
    act(() =>
      Array.from(host.querySelectorAll("button"))
        .find((b) => b.textContent === "Edit event")!
        .click(),
    );
    expect(host.querySelector('input[aria-label="Title"]')).not.toBeNull();
    const save = Array.from(host.querySelectorAll("button")).find(
      (button) => button.textContent === "Save",
    )!;
    expect(save.disabled).toBe(true);
    await act(async () => root.render(<EventPanel {...props} hasChanges />));
    expect(save.disabled).toBe(false);
  } finally {
    act(() => root.unmount());
  }
});
it("read-only events expose reading actions without editing or planning controls", async () => {
  const host = document.createElement("div"),
    root = createRoot(host);
  try {
    await act(async () =>
      root.render(
        <EventPanel
          {...props}
          draft={{
            ...event,
            external_refs: {
              ...event.external_refs,
              provider_calendar_access_role: "reader",
            },
          }}
        >
          <button>Planning control</button>
        </EventPanel>,
      ),
    );
    expect(host.textContent).toContain("read-only access");
    expect(host.textContent).not.toContain("Planning control");
    expect(host.textContent).not.toContain("Edit event");
    expect(host.textContent).not.toContain("Delete");
  } finally {
    act(() => root.unmount());
  }
});
it("adding and removing a reminder preserves every other reminder and its delivery method", async () => {
  const host = document.createElement("div"),
    root = createRoot(host),
    change = vi.fn();
  const reminders = [
    { method: "popup", minutes_before: 10 },
    { method: "email", minutes_before: 60 },
  ];
  try {
    await act(async () =>
      root.render(
        <EventReminders
          draft={{ ...event, reminders_use_default: false, reminders }}
          onChange={change}
        />,
      ),
    );
    act(() =>
      Array.from(host.querySelectorAll("button"))
        .find((b) => b.textContent === "Add reminder")!
        .click(),
    );
    expect(change.mock.calls[0][0].reminders.slice(0, 2)).toEqual(reminders);
    act(() =>
      host
        .querySelector<HTMLButtonElement>('[aria-label="Remove reminder 1"]')!
        .click(),
    );
    expect(change.mock.calls[1][0].reminders).toEqual([reminders[1]]);
  } finally {
    act(() => root.unmount());
  }
});
it("renders formatted descriptions without executing HTML or unsafe links", async () => {
  const host = document.createElement("div"),
    root = createRoot(host);
  try {
    await act(async () =>
      root.render(
        <EventDescription
          text={
            '<p>Agenda <strong>important</strong><a href="javascript:alert(1)">Unsafe</a><a href="https://example.com">https://example.com</a></p><script>bad()</script><img src=x onerror="bad()">'
          }
        />,
      ),
    );
    expect(host.querySelector("strong")?.textContent).toBe("important");
    expect(host.querySelectorAll("a")).toHaveLength(1);
    expect(host.querySelector("script, img")).toBeNull();
    expect(host.textContent).not.toContain("bad()");
  } finally {
    act(() => root.unmount());
  }
});
