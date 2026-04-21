import type { RuntimeEvent } from "../api/client";

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function normalizeLabel(value: string): string {
  return value
    .replace(/\u001b\[[0-9;]*m/g, "")
    .replace(/\u2026/g, "...")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[._-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function providerJsonLabelType(value: string): string {
  const normalized = value.trim();
  if (!normalized.startsWith("{") || !normalized.endsWith("}")) {
    return "";
  }
  try {
    const payload = JSON.parse(normalized) as { type?: unknown };
    return typeof payload.type === "string" ? payload.type : "";
  } catch {
    return "";
  }
}

export function isNoisyRuntimeLabel(label: string): boolean {
  const normalized = normalizeLabel(label);
  const isNoisyProviderTelemetry =
    normalized.startsWith("account rate limits") ||
    normalized.startsWith("thread token usage") ||
    normalized.startsWith("thread status");

  return (
    normalized.includes("reading additional input from stdin") ||
    normalized === "thread started" ||
    normalized === "turn started" ||
    normalized === "turn completed" ||
    normalized === "turn diff updated" ||
    normalized === "skills changed" ||
    normalized === "item started" ||
    normalized === "item completed" ||
    isNoisyProviderTelemetry
  );
}

export function runtimeStepLabel(event: RuntimeEvent): string | null {
  if (event.event_type !== "runtime.step.updated") {
    return null;
  }
  const label = stringValue(event.payload.label) || stringValue(event.payload.message) || stringValue(event.payload.provider_event_type);
  if (!label || providerJsonLabelType(label) || isNoisyRuntimeLabel(label)) {
    return null;
  }
  return label;
}

export function latestRuntimeStepLabel(events: RuntimeEvent[], turnId?: string | null): string {
  for (const event of [...events].reverse()) {
    if (turnId && event.turn_id !== turnId) {
      continue;
    }
    const label = runtimeStepLabel(event);
    if (label) {
      return label;
    }
  }
  return "";
}
