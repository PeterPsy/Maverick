// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  LiveNotificationFeed,
  type LiveNotification,
} from "./live-notification-feed";

let root: Root;
let host: HTMLDivElement;
let reduced = false;
const items: LiveNotification[] = [
  { id: "first", kind: "generic", app: "Jobs", title: "First" },
  { id: "second", kind: "generic", app: "Jobs", title: "Second" },
];
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.useFakeTimers();
  reduced = false;
  vi.spyOn(window, "matchMedia").mockImplementation(
    () =>
      ({
        matches: reduced,
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList,
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.restoreAllMocks();
});
const advance = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

it("animates replacement calendar sheets after a same-id date update", async () => {
  const animate = vi.fn(() => ({ cancel: vi.fn() }) as unknown as Animation);
  const originalAnimate = Object.getOwnPropertyDescriptor(
    HTMLElement.prototype,
    "animate",
  );
  Object.defineProperty(HTMLElement.prototype, "animate", {
    configurable: true,
    value: animate,
  });
  try {
    const calendar: LiveNotification = {
      id: "calendar",
      kind: "calendar",
      app: "Calendar",
      title: "Appointment",
      date: "2026-10-15",
    };
    await act(async () => root.render(<LiveNotificationFeed items={[]} />));
    await act(async () =>
      root.render(<LiveNotificationFeed items={[calendar]} />),
    );
    const previous = Array.from(host.querySelector("[data-sheets]")!.children);
    expect(previous.every((sheet) => animate.mock.contexts.includes(sheet))).toBe(
      true,
    );
    await advance(1500);
    await act(async () =>
      root.render(
        <LiveNotificationFeed items={[{ ...calendar, date: "2026-10-20" }]} />,
      ),
    );
    expect(host.querySelector('[aria-label="2026-10-20"]')).not.toBeNull();
    const current = Array.from(host.querySelector("[data-sheets]")!.children);
    expect(current).toHaveLength(4);
    expect(current.every((sheet) => !previous.includes(sheet))).toBe(true);
    expect(current.every((sheet) => animate.mock.contexts.includes(sheet))).toBe(
      true,
    );
  } finally {
    if (originalAnimate)
      Object.defineProperty(HTMLElement.prototype, "animate", originalAnimate);
    else Reflect.deleteProperty(HTMLElement.prototype, "animate");
  }
});

it("replays appended demo arrivals, pauses for focus and restarts the loop", async () => {
  await act(async () =>
    root.render(
      <LiveNotificationFeed
        items={items}
        autoplay
        initial={0}
        interval={100}
        loop
      />,
    ),
  );
  await advance(450);
  expect(host.querySelectorAll("[data-notification]")).toHaveLength(1);
  const button = host.querySelector<HTMLButtonElement>("[data-open]")!;
  act(() => button.focus());
  await advance(1000);
  expect(host.querySelectorAll("[data-notification]")).toHaveLength(1);
  act(() => button.blur());
  await advance(400);
  expect(host.querySelectorAll("[data-notification]")).toHaveLength(2);
  await advance(800);
  expect(host.querySelector("[data-empty]")).not.toBeNull();
  await advance(950);
  expect(host.querySelectorAll("[data-notification]")).toHaveLength(1);
});

it("shows reduced-motion demo detail immediately without replaying arrivals", async () => {
  reduced = true;
  await act(async () =>
    root.render(
      <LiveNotificationFeed
        items={items}
        autoplay
        initial={0}
        interval={100}
        loop
      />,
    ),
  );
  expect(host.querySelectorAll("[data-notification]")).toHaveLength(2);
  await advance(3000);
  expect(host.querySelectorAll("[data-notification]")).toHaveLength(2);
});

it("keeps absolute code expiry across card remounts", async () => {
  const code: LiveNotification = {
    id: "otp",
    kind: "code",
    app: "Account",
    title: "Code",
    code: "482913",
    expiresIn: 1,
    expiresAt: new Date(Date.now() + 1000).toISOString(),
  };
  await act(async () => root.render(<LiveNotificationFeed items={[code]} />));
  await advance(1000);
  expect(host.querySelector<HTMLButtonElement>("[data-copy]")!.disabled).toBe(
    true,
  );
  await act(async () =>
    root.render(<LiveNotificationFeed key="reopened" items={[code]} />),
  );
  expect(host.querySelector<HTMLButtonElement>("[data-copy]")!.disabled).toBe(
    true,
  );
});
