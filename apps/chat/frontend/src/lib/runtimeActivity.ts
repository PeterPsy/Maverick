import type { RuntimeEvent, RuntimeTurn } from "../api/client";
import { isNonChatFacingProviderEvent, runtimeStepLabel } from "./runtimeStepLabels";

export type RuntimeActivityLabelOptions = {
  activeTurn?: RuntimeTurn | null;
  events: RuntimeEvent[];
  isBootstrapping?: boolean;
  isHistoryLoading?: boolean;
  isRuntimeBusy?: boolean;
  isSending?: boolean;
};

export function runtimeActivityLabel({
  activeTurn = null,
  events,
  isBootstrapping = false,
  isHistoryLoading = false,
  isRuntimeBusy = false,
  isSending = false,
}: RuntimeActivityLabelOptions): string {
  if (isHistoryLoading) {
    return "Loading history";
  }
  if (isBootstrapping) {
    return "Loading chat";
  }
  if (!isRuntimeBusy && isSending) {
    return "Starting";
  }
  if (!isRuntimeBusy) {
    return "";
  }
  if (!activeTurn) {
    return "";
  }
  if (activeTurn?.status === "queued") {
    return "Queued";
  }
  if (activeTurn?.status && activeTurn.status !== "active") {
    return "";
  }
  return activeTurnActivityLabel(events, activeTurn.turn_id) || "Thinking";
}

function activeTurnActivityLabel(events: RuntimeEvent[], turnId?: string | null): string {
  for (const event of [...events].reverse()) {
    if (turnId && event.turn_id !== turnId) {
      continue;
    }
    const label = eventActivityLabel(event);
    if (label !== null) {
      return label;
    }
  }
  return "";
}

function eventActivityLabel(event: RuntimeEvent): string | null {
  if (event.event_type === "runtime.output.delta") {
    return "Writing";
  }
  if (event.event_type === "runtime.output.structured") {
    return "Preparing result";
  }
  if (event.event_type === "runtime.output.final") {
    return "Finalizing";
  }
  if (event.event_type === "runtime.turn.queued") {
    return "Queued";
  }
  if (event.event_type === "runtime.turn.worker_started") {
    return "Preparing runtime";
  }
  if (event.event_type === "runtime.provider.dispatching") {
    return "Starting model";
  }
  if (event.event_type === "runtime.provider.accepted") {
    return "Thinking";
  }
  if (event.event_type === "runtime.turn.started") {
    return "Thinking";
  }
  if (event.event_type.startsWith("runtime.tool_call.")) {
    return toolActivityLabel(event);
  }
  const stepLabel = runtimeStepLabel(event);
  if (stepLabel) {
    return stepLabel;
  }
  return null;
}

function toolActivityLabel(event: RuntimeEvent): string | null {
  if (isNonChatFacingProviderEvent(event.payload.provider_event_type) || isNonChatFacingProviderEvent(event.payload.name)) {
    return null;
  }
  const status = event.event_type.split(".").at(-1) || "";
  if (status === "completed") {
    return "Thinking";
  }
  if (status === "failed") {
    return "Tool failed";
  }
  if (status !== "started" && status !== "updated") {
    return null;
  }
  return activeToolLabel(event.payload);
}

function activeToolLabel(payload: Record<string, unknown>): string {
  const toolKind = stringValue(payload.tool_kind);
  if (toolKind === "web_search") {
    return "Searching web";
  }
  if (toolKind === "file_change") {
    return "Editing files";
  }
  if (toolKind === "skill_change") {
    return "Updating skills";
  }
  if (toolKind === "command") {
    return commandActivityLabel(stringValue(payload.command));
  }
  const command = stringValue(payload.command);
  if (command) {
    return commandActivityLabel(command);
  }
  const name = (stringValue(payload.name) || stringValue(payload.tool_name) || stringValue(payload.tool)).toLowerCase();
  if (name.includes("web")) {
    return "Searching web";
  }
  if (name.includes("file")) {
    return "Working with files";
  }
  return "Using tool";
}

function commandActivityLabel(command: string): string {
  if (!command) {
    return "Running command";
  }
  const normalized = command.toLowerCase();
  if (/(^|\s)(rg|find|ls|pwd)(\s|$)/.test(normalized) || normalized.includes("rg --files")) {
    return "Searching files";
  }
  if (/(^|\s)(cat|sed|tail|head|nl)(\s|$)/.test(normalized)) {
    return "Reading files";
  }
  if (/(^|\s)(cp|mv|mkdir|touch)(\s|$)/.test(normalized) || normalized.includes("apply_patch")) {
    return "Editing files";
  }
  return "Running command";
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}
