import type { ReadModelRequest } from "./readModelRetry";

export function describeReadModelRequest(request: ReadModelRequest): { endpoint: string; body?: string } {
  const parameters = JSON.parse(JSON.stringify(request.parameters ?? {})) as Record<string, unknown>;
  const identity = `${request.appId}/${request.resource}`;
  let action: string;
  let fields: string[];
  switch (identity) {
    case "app-store/catalog":
      if (Object.keys(parameters).length) throw new TypeError("Catalog GET takes no parameters.");
      return { endpoint: "/api/app-store/apps" };
    case "calendar/bounded-event-window":
      action = "pwa.read_model";
      fields = ["kind", "start_after", "end_before", "offset", "event_id", "known_revision"];
      if (!["window", "event"].includes(String(parameters.kind))) throw new TypeError("Invalid Calendar read kind.");
      break;
    case "crm/lists-and-recent-records":
      action = "pwa.read_model";
      fields = ["kind", "query", "entity_type", "id", "filters", "cursor", "limit", "sort_field", "sort_direction", "pipeline_id", "known_revision"];
      if (!["records_table", "schema", "pipeline_board", "get", "search", "bootstrap"].includes(String(parameters.kind))) throw new TypeError("Invalid CRM read kind.");
      break;
    case "mail/thread-headers-snippets-and-bodies":
      action = "pwa.read_model";
      fields = ["kind", "mailbox", "mailbox_scopes", "connection_id", "query", "max_threads", "offset", "thread_id", "message_id", "max_body_chars", "max_body_html_chars", "known_revision"];
      if (!["mailboxes", "threads", "thread", "message"].includes(String(parameters.kind))) throw new TypeError("Invalid Mail read kind.");
      break;
    case "storage/file-catalog":
      action = "catalog";
      fields = ["query", "role", "kind", "folder_path", "offset", "limit", "file_ids", "workspace_relative_paths", "known_revision"];
      if (parameters.offset !== undefined && parameters.offset !== 0) throw new TypeError("Only the initial catalog page is approved.");
      break;
    case "website-studio/site-snapshots":
      action = "workspace_snapshot";
      fields = ["site_id", "route", "known_revision"];
      break;
    case "fitness-coach/sanitized-bootstrap-and-thumbnails":
      action = "app.bootstrap";
      fields = ["include_runs", "selected_workout_id", "storage_app_id", "known_revision"];
      break;
    default:
      throw new TypeError("Read-model retry requires an SDK-reviewed app/resource.");
  }
  if (!parameters || Array.isArray(parameters) || Object.keys(parameters).some((field) => !fields.includes(field))) {
    throw new TypeError("Read-model retry parameters are outside the reviewed read contract.");
  }
  const body = JSON.stringify({
    ...parameters, action,
    ...(request.appId === "storage" ? { _app_secret_request: { logical_names: [], required: false } } : {}),
  });
  if (body.length > 16_384) throw new TypeError("Read-model retry request exceeds its budget.");
  return { endpoint: `/api/apps/${request.appId}/backend`, body };
}
