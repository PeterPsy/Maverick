import type { StorageEstimate, StorageQuotaAdapter } from "./types";

const DEFAULT_QUOTA_HEADROOM_RATIO = 0.85;

export class BrowserStorageQuotaAdapter implements StorageQuotaAdapter {
  constructor(private readonly headroomRatio = DEFAULT_QUOTA_HEADROOM_RATIO) {}

  async estimate(): Promise<StorageEstimate> {
    const storage = globalThis.navigator?.storage;
    if (!storage || typeof storage.estimate !== "function") {
      return { quota: null, supported: false, usage: null };
    }
    try {
      const estimate = await storage.estimate();
      return {
        quota: finiteNonNegative(estimate.quota),
        supported: true,
        usage: finiteNonNegative(estimate.usage),
      };
    } catch {
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
}

function finiteNonNegative(value: number | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}
