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

describe("WP0 current sidecar mount limitation", () => {
  it("characterizes an OpenDesign absolute API URL escaping the path-mounted sidecar", () => {
    const mountedDocument =
      "https://maverick.example/api/apps/design-studio/sidecars/opendesign/index.html";

    const resolved = new URL("/api/projects", mountedDocument);

    expect(resolved.pathname).toBe("/api/projects");
    expect(resolved.pathname).not.toContain("/sidecars/opendesign/");
  });
});
