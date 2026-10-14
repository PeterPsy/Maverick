import { afterEach, expect, it } from "vitest";
import {
  isLoopinoParentMessage,
  mountedAppIdFromPath,
  viewFromAppPage,
} from "./shellNavigation";

type FrameWindow = Window & {
  __LOOPINO_PLATFORM_ORIGIN__?: string;
  __LOOPINO_APP_FRAME_CONTEXT__?: unknown;
};
afterEach(() => {
  delete (window as FrameWindow).__LOOPINO_PLATFORM_ORIGIN__;
  delete (window as FrameWindow).__LOOPINO_APP_FRAME_CONTEXT__;
});

it("uses the Core-injected local app binding and accepts only the exact shell", () => {
  (window as FrameWindow).__LOOPINO_PLATFORM_ORIGIN__ =
    "https://loopino.example";
  (window as FrameWindow).__LOOPINO_APP_FRAME_CONTEXT__ = {
    app_id: "marta-team",
    workspace_id: "team",
  };
  expect(mountedAppIdFromPath("/apps/marta-ops/")).toBe("marta-team");
  expect(
    isLoopinoParentMessage(
      new MessageEvent("message", {
        origin: "https://loopino.example",
        source: window,
        data: {},
      }),
    ),
  ).toBe(true);
  expect(
    isLoopinoParentMessage(
      new MessageEvent("message", {
        origin: window.location.origin,
        source: window,
        data: {},
      }),
    ),
  ).toBe(false);
  expect(
    isLoopinoParentMessage(
      new MessageEvent("message", {
        origin: "https://loopino.example",
        source: null,
        data: {},
      }),
    ),
  ).toBe(false);
  expect(viewFromAppPage("contacts")).toBe("contacts");
  expect(viewFromAppPage("tasks")).toBe("tasks");
  expect(viewFromAppPage("deliveries")).toBe("deliveries");
  expect(viewFromAppPage("admin")).toBe("admin");
});
