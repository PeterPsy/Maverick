import { describe, expect, it } from "vitest";

import {
  currentDesignStudioAppId,
  nativeOpenDesignPath,
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
  sidecar_instance_id: "instance_12345678",
};

describe("native OpenDesign deep links", () => {
  it("keeps root, project, and exact conversation routes native", () => {
    expect(nativeOpenDesignPath("")).toBe("/");
    expect(nativeOpenDesignPath({ od_project_id: "project_1" })).toBe("/projects/project_1");
    expect(nativeOpenDesignPath({
      od_project_id: "project_1",
      od_conversation_id: "conversation_1",
    })).toBe("/projects/project_1/conversations/conversation_1");
  });

  it("rejects path-shaped identifiers instead of interpreting them", () => {
    expect(nativeOpenDesignPath({
      od_project_id: "../project",
      od_conversation_id: "conversation_1",
    })).toBe("/");
    expect(currentDesignStudioAppId("/apps/workspace-design-studio")).toBe("workspace-design-studio");
  });
});

describe("isolated browser launch validation", () => {
  it("accepts a one-shot cross-origin POST bootstrap", () => {
    expect(validateSidecarLaunch(VALID_LAUNCH, "https://maverick.example")).toEqual(VALID_LAUNCH);
    expect(VALID_LAUNCH.bootstrap_url).not.toContain(VALID_LAUNCH.ticket);
  });

  it("rejects same-origin, query-bearing, and overlong capabilities", () => {
    for (const candidate of [
      { ...VALID_LAUNCH, origin: "https://maverick.example", bootstrap_url: "https://maverick.example/.well-known/maverick-sidecar-bootstrap" },
      { ...VALID_LAUNCH, bootstrap_url: `${VALID_LAUNCH.bootstrap_url}?ticket=leaked` },
      { ...VALID_LAUNCH, ticket: "x".repeat(513) },
    ]) {
      expect(() => validateSidecarLaunch(candidate, "https://maverick.example")).toThrow(SidecarLaunchError);
    }
  });
});
