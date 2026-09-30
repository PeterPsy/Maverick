import { afterEach, expect, it } from "vitest";
import {
  isMaverickParentMessage,
  mountedAppIdFromPath,
  viewFromAppPage,
} from "./shellNavigation";

type FrameWindow = Window & {
  __MAVERICK_PLATFORM_ORIGIN__?: string;
  __MAVERICK_APP_FRAME_CONTEXT__?: unknown;
};
afterEach(() => {
  delete (window as FrameWindow).__MAVERICK_PLATFORM_ORIGIN__;
  delete (window as FrameWindow).__MAVERICK_APP_FRAME_CONTEXT__;
});

it("uses the Core-injected local app binding and accepts only the exact shell", () => {
  (window as FrameWindow).__MAVERICK_PLATFORM_ORIGIN__ =
    "https://maverick.example";
  (window as FrameWindow).__MAVERICK_APP_FRAME_CONTEXT__ = {
    app_id: "marta-team",
    workspace_id: "team",
  };
  expect(mountedAppIdFromPath("/apps/marta-ops/")).toBe("marta-team");
  expect(
    isMaverickParentMessage(
      new MessageEvent("message", {
        origin: "https://maverick.example",
        source: window,
        data: {},
      }),
    ),
  ).toBe(true);
  expect(
    isMaverickParentMessage(
      new MessageEvent("message", {
        origin: window.location.origin,
        source: window,
        data: {},
      }),
    ),
  ).toBe(false);
  expect(
    isMaverickParentMessage(
      new MessageEvent("message", {
        origin: "https://maverick.example",
        source: null,
        data: {},
      }),
    ),
  ).toBe(false);
  expect(viewFromAppPage("contacts")).toBe("contacts");
  expect(viewFromAppPage("tasks")).toBe("tasks");
});
