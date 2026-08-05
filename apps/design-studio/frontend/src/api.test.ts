import { describe, expect, it } from "vitest";

import {
  currentDesignStudioAppId,
  isTrustedSidecarMessage,
  navigationFromParams,
  navigationMessage,
  openDesignPath,
  SidecarLaunchError,
  validateSidecarLaunch,
} from "./api";

const VALID_LAUNCH = {
  origin: "https://sc-proof.sidecars.example",
  bootstrap_url: "https://sc-proof.sidecars.example/.well-known/maverick-sidecar-bootstrap",
  method: "POST" as const,
  ticket_field: "ticket" as const,
  ticket: "one-shot-ticket",
  expires_in_seconds: 30,
};

describe("currentDesignStudioAppId", () => {
  it("reads the mounted app id and keeps a bounded fallback", () => {
    expect(currentDesignStudioAppId("/apps/design-studio/projects")).toBe("design-studio");
    expect(currentDesignStudioAppId("/apps/workspace-design-studio")).toBe("workspace-design-studio");
    expect(currentDesignStudioAppId("/")).toBe("design-studio");
  });
});

describe("OpenDesign scalar navigation", () => {
  it("builds the real OpenDesign project route and forwards a versioned run hint", () => {
    const navigation = navigationFromParams({
      od_project_id: "od_project/prohibited",
      project_id: "od_project_1",
      od_run_id: "od_run_1",
    });
    expect(navigation).toEqual({ od_project_id: "", od_run_id: "od_run_1" });

    const canonical = navigationFromParams({ od_project_id: "od_project_1", od_run_id: "od_run_1" });
    expect(openDesignPath(canonical)).toBe("/projects/od_project_1");
    expect(navigationMessage(canonical)).toEqual({
      type: "maverick.opendesign.navigate",
      version: 1,
      od_project_id: "od_project_1",
      od_run_id: "od_run_1",
    });
  });

  it("does not interpret fragments or non-scalar values", () => {
    expect(navigationFromParams({ od_project_id: true, od_run_id: null })).toEqual({
      od_project_id: "",
      od_run_id: "",
    });
    expect(openDesignPath({ od_project_id: "", od_run_id: "" })).toBe("/index.html");
  });
});

describe("isolated browser launch validation", () => {
  it("accepts a clean, cross-origin POST bootstrap without a ticket in its URL", () => {
    expect(validateSidecarLaunch(VALID_LAUNCH, "https://maverick.example")).toEqual(VALID_LAUNCH);
    expect(VALID_LAUNCH.bootstrap_url).not.toContain(VALID_LAUNCH.ticket);
  });

  it("rejects platform-origin, query-bearing, and overlong ticket responses", () => {
    for (const candidate of [
      { ...VALID_LAUNCH, origin: "https://maverick.example", bootstrap_url: "https://maverick.example/.well-known/maverick-sidecar-bootstrap" },
      { ...VALID_LAUNCH, bootstrap_url: `${VALID_LAUNCH.bootstrap_url}?ticket=leaked` },
      { ...VALID_LAUNCH, ticket: "x".repeat(513) },
    ]) {
      expect(() => validateSidecarLaunch(candidate, "https://maverick.example")).toThrow(SidecarLaunchError);
    }
  });
});

describe("sidecar postMessage boundary", () => {
  it("requires both the exact isolated origin and iframe source", () => {
    const frameWindow = {} as Window;
    expect(isTrustedSidecarMessage(
      { origin: VALID_LAUNCH.origin, source: frameWindow },
      VALID_LAUNCH.origin,
      frameWindow,
    )).toBe(true);
    expect(isTrustedSidecarMessage(
      { origin: "https://evil.example", source: frameWindow },
      VALID_LAUNCH.origin,
      frameWindow,
    )).toBe(false);
    expect(isTrustedSidecarMessage(
      { origin: VALID_LAUNCH.origin, source: {} as Window },
      VALID_LAUNCH.origin,
      frameWindow,
    )).toBe(false);
  });
});
