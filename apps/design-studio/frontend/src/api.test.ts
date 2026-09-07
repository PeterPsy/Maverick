import { afterEach, describe, expect, it, vi } from "vitest";

import {
  currentDesignStudioAppId,
  nativeOpenDesignPath,
  redeemOpenDesignBootstrap,
  requestOpenDesignBootstrapStatus,
  SidecarLaunchError,
  validateSidecarLaunch,
} from "./api";

const VALID_LAUNCH = {
  origin: "https://sc-proof.sidecars.example",
  bootstrap_url: "https://sc-proof.sidecars.example/.well-known/maverick-sidecar-bootstrap",
  bootstrap_transport: "cors" as const,
  method: "POST" as const,
  parent_origin: "https://af-design.sidecars.example",
  ticket_field: "ticket" as const,
  ticket: "one-shot-ticket",
  target_url: "https://sc-proof.sidecars.example/",
  confirmation_token: "bootstrap-confirmation-token",
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
    expect(nativeOpenDesignPath({
      app_page: "projects/project_2/conversations/conversation_2",
    })).toBe("/projects/project_2/conversations/conversation_2");
  });

  it("rejects path-shaped identifiers instead of interpreting them", () => {
    expect(nativeOpenDesignPath({
      od_project_id: "../project",
      od_conversation_id: "conversation_1",
    })).toBe("/");
    expect(nativeOpenDesignPath({
      app_page: "projects/project_1/conversations/../private",
      od_project_id: "stale_query_project",
    })).toBe("/");
    expect(currentDesignStudioAppId("/apps/workspace-design-studio")).toBe("workspace-design-studio");
  });
});

describe("isolated browser launch validation", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("accepts a one-shot cross-origin POST bootstrap", () => {
    expect(validateSidecarLaunch(
      VALID_LAUNCH,
      "https://maverick.example",
      VALID_LAUNCH.parent_origin,
      "/",
    )).toEqual(VALID_LAUNCH);
    expect(VALID_LAUNCH.bootstrap_url).not.toContain(VALID_LAUNCH.ticket);
  });

  it("rejects same-origin, query-bearing, and overlong capabilities", () => {
    for (const candidate of [
      { ...VALID_LAUNCH, origin: "https://maverick.example", bootstrap_url: "https://maverick.example/.well-known/maverick-sidecar-bootstrap" },
      { ...VALID_LAUNCH, bootstrap_url: `${VALID_LAUNCH.bootstrap_url}?ticket=leaked` },
      { ...VALID_LAUNCH, target_url: `${VALID_LAUNCH.origin}/projects/other` },
      { ...VALID_LAUNCH, parent_origin: "https://af-attacker.sidecars.example" },
      { ...VALID_LAUNCH, ticket: "x".repeat(513) },
      { ...VALID_LAUNCH, confirmation_token: undefined },
    ]) {
      expect(() => validateSidecarLaunch(
        candidate,
        "https://maverick.example",
        VALID_LAUNCH.parent_origin,
        "/",
      )).toThrow(SidecarLaunchError);
    }
  });

  it("redeems a parent-bound ticket with credentialed CORS before navigation", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204 });
    vi.stubGlobal("fetch", fetchMock);

    await expect(redeemOpenDesignBootstrap(VALID_LAUNCH)).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      VALID_LAUNCH.bootstrap_url,
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        mode: "cors",
        redirect: "error",
        body: "ticket=one-shot-ticket",
      }),
    );
  });

  it("requires an authenticated Core confirmation for the redeemed bootstrap", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ status: "ready" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      requestOpenDesignBootstrapStatus("design-studio", VALID_LAUNCH),
    ).resolves.toBe("ready");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/app-sidecars/browser-launch-status",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
        body: JSON.stringify({
          app_id: "design-studio",
          sidecar_id: "opendesign",
          sidecar_instance_id: VALID_LAUNCH.sidecar_instance_id,
          confirmation_token: VALID_LAUNCH.confirmation_token,
        }),
      }),
    );
  });
});
