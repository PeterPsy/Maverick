import { shellCommandActivityLabel } from "./shellCommandPresentation";
import { labelForStatus, statusLabels, type ToolActivityStatus } from "./toolActivityStatus";

type ToolPresentationInput = {
  detail: Record<string, unknown>;
  name?: string;
  status: ToolActivityStatus;
};

const MAX_FRAGMENT_LENGTH = 80;
const MAX_LABEL_LENGTH = 112;

export function toolActivityLabel({ detail, name = "", status }: ToolPresentationInput): string {
  const toolKind = stringValue(detail.tool_kind);
  const command = stringValue(detail.command) || stringValue(detail.cmd);
  if (toolKind === "command" || command) return shellCommandActivityLabel(command, status);
  if (toolKind === "web_search" || isWebTool(detail, name)) return webSearchLabel(detail, status);
  if (toolKind === "file_change" || name === "file_change") return fileChangeLabel(detail, status);
  if (toolKind === "device_use" || ["mac_computer", "mac_peekaboo", "mac_calendar"].includes(name)) {
    return deviceUseLabel(detail, status);
  }
  if (toolKind === "skill_change") {
    return statusLabel(status, "Updating skills", "Updated skills", "Failed to update skills", "Ready to update skills");
  }
  return handleLabel(stringValue(detail.tool_handle) || name, status);
}

function deviceUseLabel(detail: Record<string, unknown>, status: ToolActivityStatus): string {
  const action = stringValue(detail.action).toLowerCase();
  if (["observe", "observe_app", "list_windows"].includes(action)) {
    return statusLabel(status, "Observing Mac app", "Observed Mac app", "Mac observation failed", "Ready to observe Mac app");
  }
  if (action === "open_app") {
    return statusLabel(status, "Opening Mac app", "Opened Mac app", "Failed to open Mac app", "Ready to open Mac app");
  }
  if (action === "select_app") {
    return statusLabel(status, "Selecting Mac app", "Selected Mac app", "Failed to select Mac app", "Ready to select Mac app");
  }
  if (["type", "type_text", "type_at_point", "replace", "replace_text", "replace_at_point"].includes(action)) {
    return statusLabel(status, "Typing in Mac app", "Typed in Mac app", "Mac typing failed", "Ready to type in Mac app");
  }
  if (action === "scroll") {
    return statusLabel(status, "Scrolling Mac app", "Scrolled Mac app", "Mac scroll failed", "Ready to scroll Mac app");
  }
  if (["keypress", "key_chord", "press", "shortcut"].includes(action)) {
    return statusLabel(status, "Using Mac keyboard", "Used Mac keyboard", "Mac keyboard action failed", "Ready to use Mac keyboard");
  }
  if (["click", "click_point", "double_click", "right_click", "middle_click", "hover", "drag"].includes(action)) {
    return statusLabel(status, "Interacting with Mac app", "Interacted with Mac app", "Mac interaction failed", "Ready to interact with Mac app");
  }
  if (action === "wait") {
    return statusLabel(status, "Waiting for Mac app", "Waited for Mac app", "Mac wait failed", "Ready to wait for Mac app");
  }
  if (action === "confirm_action") {
    return statusLabel(status, "Requesting Mac confirmation", "Requested Mac confirmation", "Mac confirmation failed", "Ready to request Mac confirmation");
  }
  if (["list_calendars", "list_events"].includes(action)) {
    return statusLabel(status, "Reading Mac calendar", "Read Mac calendar", "Failed to read Mac calendar", "Ready to read Mac calendar");
  }
  if (["create_event", "update_event"].includes(action)) {
    return statusLabel(status, "Updating Mac calendar", "Updated Mac calendar", "Failed to update Mac calendar", "Ready to update Mac calendar");
  }
  return statusLabel(status, "Using Mac", "Used Mac", "Mac action failed", "Ready to use Mac");
}

function webSearchLabel(detail: Record<string, unknown>, status: ToolActivityStatus): string {
  const query = boundedFragment(stringValue(detail.query));
  const suffix = query ? ` for “${query}”` : "";
  return statusLabel(
    status,
    `Searching the web${suffix}`,
    `Searched the web${suffix}`,
    `Web search failed${suffix}`,
    `Ready to search the web${suffix}`,
  );
}

function fileChangeLabel(detail: Record<string, unknown>, status: ToolActivityStatus): string {
  const changes = arrayRecords(detail.changes);
  if (changes.length !== 1) {
    const object = changes.length > 1 ? `${changes.length} files` : "files";
    return statusLabel(status, `Editing ${object}`, `Edited ${object}`, `Failed to edit ${object}`, `Ready to edit ${object}`);
  }
  const change = changes[0];
  const path = displayPath(stringValue(change.path) || "file");
  const movePath = displayPath(stringValue(change.movePath));
  const changeType = stringValue(change.changeType).toLowerCase();
  if (changeType === "add" || changeType === "create") {
    return statusLabel(status, `Creating ${path}`, `Created ${path}`, `Failed to create ${path}`, `Ready to create ${path}`);
  }
  if (changeType === "delete") {
    return statusLabel(status, `Deleting ${path}`, `Deleted ${path}`, `Failed to delete ${path}`, `Ready to delete ${path}`);
  }
  if (changeType === "move") {
    const destination = movePath ? ` to ${movePath}` : "";
    return statusLabel(status, `Moving ${path}${destination}`, `Moved ${path}${destination}`, `Failed to move ${path}${destination}`, `Ready to move ${path}${destination}`);
  }
  return statusLabel(status, `Editing ${path}`, `Edited ${path}`, `Failed to edit ${path}`, `Ready to edit ${path}`);
}

function handleLabel(handle: string, status: ToolActivityStatus): string {
  const normalized = handle.toLowerCase();
  if (normalized.includes("filesystem.list")) {
    return statusLabel(status, "Listing workspace files", "Listed workspace files", "Workspace file listing failed", "Ready to list workspace files");
  }
  if (normalized.includes("filesystem.read")) {
    return statusLabel(status, "Reading a workspace file", "Read a workspace file", "Failed to read a workspace file", "Ready to read a workspace file");
  }
  if (normalized.includes("filesystem.write")) {
    return statusLabel(status, "Editing a workspace file", "Edited a workspace file", "Failed to edit a workspace file", "Ready to edit a workspace file");
  }
  if (normalized.includes("shell.run")) {
    return statusLabel(status, "Running a shell command", "Ran a shell command", "Shell command failed", "Ready to run a shell command");
  }

  const words = handleWords(handle);
  const resource = resourceName(words);
  if (words.includes("search") || words.includes("find")) {
    return statusLabel(status, `Searching ${resource}`, `Searched ${resource}`, `Search failed in ${resource}`, `Ready to search ${resource}`);
  }
  if (words.includes("read") || words.includes("get") || words.includes("list")) {
    return statusLabel(status, `Reading from ${resource}`, `Read from ${resource}`, `Failed to read from ${resource}`, `Ready to read from ${resource}`);
  }
  if (words.includes("write") || words.includes("create") || words.includes("update") || words.includes("set")) {
    return statusLabel(status, `Updating ${resource}`, `Updated ${resource}`, `Failed to update ${resource}`, `Ready to update ${resource}`);
  }
  if (words.includes("delete") || words.includes("remove")) {
    return statusLabel(status, `Deleting from ${resource}`, `Deleted from ${resource}`, `Failed to delete from ${resource}`, `Ready to delete from ${resource}`);
  }
  const toolName = humanizeHandle(handle) || "tool";
  return statusLabel(status, `Using ${toolName}`, `Used ${toolName}`, `${capitalize(toolName)} failed`, `Ready to use ${toolName}`);
}

function statusLabel(status: ToolActivityStatus, active: string, completed: string, failed: string, waiting: string): string {
  return boundLabel(labelForStatus(status, statusLabels(active, completed, failed, waiting)));
}

function isWebTool(detail: Record<string, unknown>, name: string): boolean {
  return stringValue(detail.provider_event_type).toLowerCase().includes("web_search") || name.toLowerCase().includes("web");
}

function handleWords(handle: string): string[] {
  return String(handle || "")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .split(/[:./_-]+|\s+/)
    .map((item) => item.toLowerCase())
    .filter((item) => item && !["app", "capability", "cli", "core", "functions", "interface", "mcp", "tool"].includes(item));
}

function resourceName(words: string[]): string {
  const actionWords = new Set(["create", "delete", "find", "get", "list", "read", "remove", "search", "set", "update", "write"]);
  const resourceWords = words.filter((word) => !actionWords.has(word));
  if (!resourceWords.length) return "tool";
  return resourceWords.map(capitalize).join(" ");
}

function humanizeHandle(handle: string): string {
  const words = handleWords(handle);
  return words.map(capitalize).join(" ");
}

function displayPath(value: string): string {
  let path = normalizeFragment(value);
  const repositoryMarker = path.match(/\/(apps|core|docs|tests|workspaces)\/.+$/)?.[0];
  if (repositoryMarker) path = repositoryMarker.slice(1);
  const segments = path.split("/").filter(Boolean);
  if (path.length > MAX_FRAGMENT_LENGTH && segments.length > 5) path = `…/${segments.slice(-5).join("/")}`;
  return boundedFragment(path);
}

function boundedFragment(value: string): string {
  const normalized = normalizeFragment(value);
  if (normalized.length <= MAX_FRAGMENT_LENGTH) return normalized;
  return `${normalized.slice(0, MAX_FRAGMENT_LENGTH - 1).trimEnd()}…`;
}

function normalizeFragment(value: string): string {
  return String(value || "").replace(/[\u0000-\u001f\u007f]+/g, " ").replace(/\s+/g, " ").trim();
}

function boundLabel(value: string): string {
  if (value.length <= MAX_LABEL_LENGTH) return value;
  return `${value.slice(0, MAX_LABEL_LENGTH - 1).trimEnd()}…`;
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function arrayRecords(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
}

function capitalize(value: string): string {
  return value ? `${value[0].toUpperCase()}${value.slice(1)}` : value;
}
