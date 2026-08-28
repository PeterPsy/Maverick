import { describe, expect, it } from "vitest";

import {
  currentDesignStudioAppId,
  isTrustedSidecarMessage,
  launchErrorIsRetryable,
  navigationFromParams,
  navigationMessage,
  openDesignPath,
  openSettingsMessage,
  openToolsMessage,
  readCachedLaunchTarget,
  SidecarLaunchError,
  validateSidecarLaunch,
  writeCachedLaunchTarget,
} from "./api";
import { BackendRequestError, mobileLayoutFromWidgetMessage, mountedAppId, nextDefaultProjectName, projectCreatedAt, projectIdFromWidgetMessage } from "./backendApi";

const VALID_LAUNCH = {
  origin: "https://sc-proof.sidecars.example",
  bootstrap_url: "https://sc-proof.sidecars.example/.well-known/maverick-sidecar-bootstrap",
  method: "POST" as const,
  ticket_field: "ticket" as const,
  ticket: "one-shot-ticket",
  expires_in_seconds: 30,
  sidecar_instance_id: "instance_12345678",
};

describe("currentDesignStudioAppId", () => {
  it("reads the mounted app id and keeps a bounded fallback", () => {
    expect(currentDesignStudioAppId("/apps/design-studio/projects")).toBe("design-studio");
    expect(currentDesignStudioAppId("/apps/workspace-design-studio")).toBe("workspace-design-studio");
    expect(currentDesignStudioAppId("/")).toBe("design-studio");
    expect(mountedAppId("/apps/workspace-design-studio/widgets/sidebar")).toBe("workspace-design-studio");
  });

  it("uses the typed native settings command", () => {
    expect(openSettingsMessage()).toEqual({ type: "maverick.opendesign.open-settings", version: 1 });
    expect(openSettingsMessage("designSystems")).toEqual({
      type: "maverick.opendesign.open-settings",
      version: 1,
      section: "designSystems",
    });
  });

  it("uses a correlated typed command for the native tools panel", () => {
    expect(openToolsMessage("tools-request-1")).toEqual({
      type: "maverick.opendesign.open-tools",
      version: 1,
      request_id: "tools-request-1",
    });
  });
});

describe("project creation ordering", () => {
  it("normalizes timestamps and never substitutes updatedAt for createdAt", () => {
    const older = { createdAt: "2026-08-01T00:00:00Z", updatedAt: "2026-08-11T00:00:00Z" };
    const newer = { created_at: 1_786_310_400, updatedAt: "2026-08-02T00:00:00Z" };
    expect(projectCreatedAt(newer)).toBeGreaterThan(projectCreatedAt(older));
    expect(projectCreatedAt({ updatedAt: "2099-01-01T00:00:00Z" })).toBe(0);
  });

  it("allocates localized default names without catalog collisions", () => {
    expect(nextDefaultProjectName([])).toBe("Progetto senza titolo");
    expect(nextDefaultProjectName([
      { name: "Progetto senza titolo" },
      { name: "progetto SENZA titolo 2" },
      { name: "Un progetto nominato" },
    ])).toBe("Progetto senza titolo 3");
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

  it("separates safe retry from artifact auto-repair semantics", () => {
    expect(launchErrorIsRetryable("browser_ticket_failed", false)).toBe(true);
    expect(launchErrorIsRetryable("sidecar_origin_unavailable", false)).toBe(true);
    expect(launchErrorIsRetryable("artifact_integrity_mismatch", false)).toBe(false);
    expect(launchErrorIsRetryable("artifact_integrity_mismatch", true)).toBe(true);
  });
});

describe("isolated launch target cache", () => {
  it("partitions non-secret target hints by the exact isolated origin", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) || null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    };
    writeCachedLaunchTarget(storage, "design-studio", VALID_LAUNCH.origin, {
      target: "project",
      od_project_id: "od_project_1",
      project: { id: "od_project_1" },
    });
    expect(readCachedLaunchTarget(storage, "design-studio", VALID_LAUNCH.origin)).toEqual({
      target: "project",
      od_project_id: "od_project_1",
      project: { id: "od_project_1" },
    });
    expect(readCachedLaunchTarget(storage, "design-studio", "https://sc-other.sidecars.example")).toBeNull();
  });

  it("drops malformed target hints and preserves typed backend diagnostics", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) || null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    };
    writeCachedLaunchTarget(storage, "design-studio", VALID_LAUNCH.origin, {
      target: "project",
      od_project_id: "../invalid",
      project: null,
    });
    expect(readCachedLaunchTarget(storage, "design-studio", VALID_LAUNCH.origin)).toBeNull();
    const error = new BackendRequestError({
      error: "artifact_integrity_mismatch",
      phase: "artifact_fast_verify",
      auto_repairable: false,
      retryable: false,
    }, 503);
    expect(error).toMatchObject({
      code: "artifact_integrity_mismatch",
      phase: "artifact_fast_verify",
      status: 503,
      retryable: false,
    });
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

describe("sidebar widget context", () => {
  it("uses shell-owned active project and mobile layout values", () => {
    const message = {
      type: "maverick.widget.context-changed",
      context: {
        content: {
          payload: {
            active_app_params: { od_project_id: "od_project_sidebar" },
            is_mobile_layout: false,
          },
        },
      },
    };
    expect(projectIdFromWidgetMessage(message)).toBe("od_project_sidebar");
    expect(mobileLayoutFromWidgetMessage(message)).toBe(false);
    expect(mobileLayoutFromWidgetMessage({ ...message, type: "untrusted" })).toBeUndefined();
  });
});
