import { createCacheLifecycleController } from "./lifecycle";
import type { CacheCleanupResult, CacheDiagnostics } from "./types";

export async function readPwaCacheDiagnostics(): Promise<CacheDiagnostics> {
  const controller = createCacheLifecycleController();
  try {
    return await controller.diagnostics();
  } finally {
    controller.dispose();
  }
}

export async function clearPwaDataCache(): Promise<CacheCleanupResult> {
  const controller = createCacheLifecycleController();
  try {
    return await controller.clearAll();
  } finally {
    controller.dispose();
  }
}
