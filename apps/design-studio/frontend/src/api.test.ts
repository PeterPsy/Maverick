import { describe, expect, it } from "vitest";

import { currentDesignStudioAppId } from "./api";

describe("currentDesignStudioAppId", () => {
  it("reads the mounted app id from an app route", () => {
    expect(currentDesignStudioAppId("/apps/design-studio/projects")).toBe("design-studio");
    expect(currentDesignStudioAppId("/apps/workspace-design-studio?tab=imports")).toBe(
      "workspace-design-studio",
    );
  });

  it("falls back to the Design Studio app id outside an app route", () => {
    expect(currentDesignStudioAppId("/")).toBe("design-studio");
    expect(currentDesignStudioAppId("/api/apps/design-studio/backend")).toBe("design-studio");
  });
});
