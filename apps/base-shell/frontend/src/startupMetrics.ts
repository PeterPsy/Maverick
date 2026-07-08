type StartupMetricEntry = {
  detail: Record<string, unknown>;
  duration_ms?: number;
  name: string;
  timestamp_ms: number;
  type: "mark" | "measure";
};

declare global {
  interface Window {
    __maverickStartupMetrics?: StartupMetricEntry[];
  }
}

function metricsEnabled(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  try {
    return window.localStorage.getItem("maverick.startupMetrics") === "1" || new URLSearchParams(window.location.search).get("startup_metrics") === "1";
  } catch {
    return false;
  }
}

function appendMetric(entry: StartupMetricEntry): void {
  if (typeof window === "undefined") {
    return;
  }
  window.__maverickStartupMetrics = [...(window.__maverickStartupMetrics ?? []), entry];
  if (metricsEnabled()) {
    console.debug("[maverick.startup]", entry);
  }
}

export function markStartupMetric(name: string, detail: Record<string, unknown> = {}): void {
  appendMetric({
    detail,
    name,
    timestamp_ms: performance.now(),
    type: "mark",
  });
}

export function measureStartupMetric(name: string, startedAtMs: number, detail: Record<string, unknown> = {}): void {
  appendMetric({
    detail,
    duration_ms: Math.max(0, Math.round((performance.now() - startedAtMs) * 100) / 100),
    name,
    timestamp_ms: performance.now(),
    type: "measure",
  });
}
