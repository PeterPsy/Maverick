import { createCacheLifecycleController } from "./lifecycle";
import type { CacheDiagnostics } from "./types";

export async function readPwaCacheDiagnostics(): Promise<CacheDiagnostics> {
  const controller = createCacheLifecycleController();
  try {
    return await controller.diagnostics();
  } finally {
    controller.dispose();
  }
}

export async function clearPwaDataCache(): Promise<number> {
  const controller = createCacheLifecycleController();
  try {
    return await controller.clearAll();
  } finally {
    controller.dispose();
  }
}
