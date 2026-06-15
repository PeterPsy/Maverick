import type { DesignStudioStatus } from "./types";

export function currentDesignStudioAppId(pathname = window.location.pathname): string {
  const match = /^\/apps\/([^/?#]+)/.exec(pathname);
  return match?.[1] || "design-studio";
}

export async function designStudioAction<T = unknown>(
  appId: string,
  action: string,
  argumentsPayload: Record<string, unknown> = {},
): Promise<T> {
  const response = await fetch(`/api/apps/${appId}/backend`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      action,
      arguments: argumentsPayload,
    }),
  });
  const payload = await response.json();
  if (!response.ok || payload.error) {
    throw new Error(payload.detail || payload.error || "Design Studio request failed.");
  }
  assertDependencyRequestsCompleted(payload);
  return payload as T;
}

export async function loadDesignStudioStatus(appId: string): Promise<DesignStudioStatus> {
  return designStudioAction<DesignStudioStatus>(appId, "state");
}

function assertDependencyRequestsCompleted(payload: unknown) {
  if (!payload || typeof payload !== "object" || !("dependency_backend_request_results" in payload)) {
    return;
  }
  const results = (payload as { dependency_backend_request_results?: unknown }).dependency_backend_request_results;
  if (!Array.isArray(results)) {
    return;
  }
  const failed = results.find((item) => item && typeof item === "object" && (item as { status?: unknown }).status !== "completed");
  if (!failed || typeof failed !== "object") {
    return;
  }
  const detail = String((failed as { error?: unknown }).error || "Design Studio dependency request failed.");
  throw new Error(detail);
}
