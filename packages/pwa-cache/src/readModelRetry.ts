import { readModelRetryTelemetry } from "./readModelRetryTelemetry";
import { RetryCoordinator } from "./retry";
import { createReadModelRequestExecutor } from "./safeRequestRetry";

export type ReadModelRequest = Readonly<{
  appId: string;
  resource: string;
  parameters?: Readonly<Record<string, unknown>>;
  etag?: string;
}>;

/** One loader invocation; only the SDK-owned, allowlisted HTTP read is retried. */
export async function readCacheModelJson<T>(request: ReadModelRequest, signal?: AbortSignal): Promise<T> {
  const executor = createReadModelRequestExecutor(request);
  const coordinator = new RetryCoordinator({ telemetry: readModelRetryTelemetry(request, signal) });
  try {
    return await coordinator.runRequest<T>({ executor, key: `${request.appId}:${request.resource}`, signal });
  } finally {
    coordinator.dispose();
  }
}

