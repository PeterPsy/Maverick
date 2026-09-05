import type { StorageEstimate, StorageQuotaAdapter, StorageQuotaTelemetry } from "./types";

const DEFAULT_QUOTA_HEADROOM_RATIO = 0.85;

export class BrowserStorageQuotaAdapter implements StorageQuotaAdapter {
  private readonly headroomRatio: number;
  private readonly telemetry: StorageQuotaTelemetry;

  constructor(options: {
    headroomRatio?: number;
    telemetry?: StorageQuotaTelemetry;
  } = {}) {
    this.headroomRatio = validHeadroomRatio(options.headroomRatio);
    this.telemetry = options.telemetry ?? (() => undefined);
  }

  async estimate(): Promise<StorageEstimate> {
    const storage = globalThis.navigator?.storage;
    if (!storage || typeof storage.estimate !== "function") {
      const estimate = { quota: null, supported: false, usage: null };
      this.emit({ kind: "estimate", ...estimate });
      return estimate;
    }
    try {
      const estimate = await storage.estimate();
      const normalized = {
        quota: finiteNonNegative(estimate.quota),
        supported: true,
        usage: finiteNonNegative(estimate.usage),
      };
      this.emit({ kind: "estimate", ...normalized });
      return normalized;
    } catch {
      this.emit({ kind: "error" });
      return { quota: null, supported: true, usage: null };
    }
  }

  async canWrite(additionalBytes: number): Promise<boolean> {
    if (!Number.isFinite(additionalBytes) || additionalBytes < 0) {
      return false;
    }
    const estimate = await this.estimate();
    if (estimate.quota === null || estimate.usage === null) {
      return false;
    }
    return estimate.usage + additionalBytes <= estimate.quota * this.headroomRatio;
  }

  private emit(event: Parameters<StorageQuotaTelemetry>[0]): void {
    try {
      this.telemetry(event);
    } catch {
      // Observability must never participate in cache or network behavior.
    }
  }
}

function validHeadroomRatio(value: number | undefined): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 && value <= 1
    ? value
    : DEFAULT_QUOTA_HEADROOM_RATIO;
}

function finiteNonNegative(value: number | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}
