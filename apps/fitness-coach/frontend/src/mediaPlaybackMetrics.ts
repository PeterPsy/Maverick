export type MediaPlaybackMetric = {
  event: string;
  timestamp: number;
  media_key?: string;
  role?: 'current' | 'preload' | 'preview';
  provider?: string;
  media_kind?: string;
  status?: string;
  drive_cache_status?: string;
  duration_ms?: number;
  ttfb_ms?: number;
  response_ms?: number;
  transfer_size?: number;
  encoded_body_size?: number;
  decoded_body_size?: number;
  ready_state?: number;
  network_state?: number;
  detail?: string;
};

declare global {
  interface Window {
    __fitnessCoachMediaMetrics?: MediaPlaybackMetric[];
    __fitnessCoachMediaMetricsDebug?: boolean;
  }
}

const MAX_MEDIA_METRICS = 160;

export function mediaMetricNow() {
  return typeof performance !== 'undefined' && typeof performance.now === 'function'
    ? performance.now()
    : Date.now();
}

export function elapsedMediaMetricMs(startedAt: number) {
  return roundMetricMs(mediaMetricNow() - startedAt);
}

export function recordMediaPlaybackMetric(metric: Omit<MediaPlaybackMetric, 'timestamp'>) {
  const entry: MediaPlaybackMetric = {
    ...metric,
    timestamp: Date.now()
  };
  if (typeof window === 'undefined') return entry;
  const metrics = window.__fitnessCoachMediaMetrics || [];
  metrics.push(entry);
  if (metrics.length > MAX_MEDIA_METRICS) {
    metrics.splice(0, metrics.length - MAX_MEDIA_METRICS);
  }
  window.__fitnessCoachMediaMetrics = metrics;
  if (window.__fitnessCoachMediaMetricsDebug) {
    // Intentionally does not include raw Storage media URLs.
    console.debug('[fitness-coach:media]', entry);
  }
  return entry;
}

export function latestMediaResourceTiming(url: string) {
  if (!url || typeof performance === 'undefined' || typeof performance.getEntriesByName !== 'function') return {};
  const names = [url];
  if (typeof window !== 'undefined') {
    try {
      names.push(new URL(url, window.location.href).href);
    } catch {
      // Keep the relative URL lookup only.
    }
  }
  for (const name of names) {
    const entries = performance.getEntriesByName(name, 'resource') as PerformanceResourceTiming[];
    const entry = entries[entries.length - 1];
    if (!entry) continue;
    return {
      ttfb_ms: roundMetricMs(entry.responseStart - entry.startTime),
      response_ms: roundMetricMs(entry.responseEnd - entry.startTime),
      duration_ms: roundMetricMs(entry.duration),
      transfer_size: entry.transferSize,
      encoded_body_size: entry.encodedBodySize,
      decoded_body_size: entry.decodedBodySize
    };
  }
  return {};
}

export function roundMetricMs(value: number) {
  return Number.isFinite(value) ? Math.max(0, Math.round(value * 10) / 10) : undefined;
}
