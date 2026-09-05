import type { RetryTelemetryEvent } from "./metricsTypes";

export const PWA_DATA_CACHE_BROKER_RETRY = "maverick.pwa.data-cache.retry.v1";

export type ParentDataCacheRetryMessage = {
  app_id: string;
  request_id: string;
  network_request_id: string;
  type: typeof PWA_DATA_CACHE_BROKER_RETRY;
  event: Pick<RetryTelemetryEvent, "attempt" | "keyHash" | "kind">;
};

type ReadScope = { appId: string; resource: string };
type Observer = ReadScope & { telemetry: (event: RetryTelemetryEvent) => void };
const observers = new WeakMap<AbortSignal, Observer>();

/** Internal, signal-scoped bridge: never grants replay authority to a loader. */
export function bindReadModelRetryTelemetry(
  signal: AbortSignal,
  scope: ReadScope,
  telemetry: Observer["telemetry"],
): () => void {
  const observer = { ...scope, telemetry };
  observers.set(signal, observer);
  return () => { if (observers.get(signal) === observer) observers.delete(signal); };
}

export function readModelRetryTelemetry(scope: ReadScope, signal?: AbortSignal): Observer["telemetry"] | undefined {
  const observer = signal ? observers.get(signal) : undefined;
  if (!observer || observer.appId !== scope.appId || observer.resource !== scope.resource) return undefined;
  return (event) => {
    // A closed or replaced broker request must not emit into a later read.
    if (signal && observers.get(signal) === observer) observer.telemetry(event);
  };
}

/** No payload, URL, entity, error text or app-provided duration reaches metrics. */
export function isParentDataCacheRetryMessage(
  value: unknown,
  scope: { appId: string; requestId: string; networkRequestId: string },
): value is ParentDataCacheRetryMessage {
  if (!value || typeof value !== "object") return false;
  const message = value as Partial<ParentDataCacheRetryMessage>;
  const event = message.event;
  return message.type === PWA_DATA_CACHE_BROKER_RETRY
    && message.app_id === scope.appId
    && message.request_id === scope.requestId
    && message.network_request_id === scope.networkRequestId
    && Boolean(event && typeof event === "object"
      && typeof event.keyHash === "string" && /^[a-f0-9]{8}$/.test(event.keyHash)
      && Number.isSafeInteger(event.attempt) && event.attempt >= 0
      && ["wait_started", "retry_attempt", "resolved", "cancelled"].includes(event.kind));
}
