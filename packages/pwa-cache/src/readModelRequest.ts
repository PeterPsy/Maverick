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
    case "chat/projects-and-completed-messages": {
      if (parameters.kind === 'projects') {
        action = 'pwa.read_model';
        fields = ['kind', 'offset', 'known_revision'];
        break;
      }
      const allowed = parameters.kind === 'threads' ? ['kind', 'limit', 'query', 'cursor', 'known_revision']
        : parameters.kind === 'messages' ? ['kind', 'session_id', 'known_revision'] : [];
      if (!allowed.length || Object.keys(parameters).some((key) => !allowed.includes(key))) throw new TypeError('Invalid Chat display read.');
      const query = new URLSearchParams({ projection: 'display' });
      for (const key of allowed.filter((key) => key !== 'kind' && key !== 'session_id')) {
        if (parameters[key] !== undefined) {
          if (!['string', 'number'].includes(typeof parameters[key]) || String(parameters[key]).length > 2048) throw new TypeError('Invalid display query.');
          query.set(key, String(parameters[key]));
        }
      }
      if (parameters.kind === 'messages' && (typeof parameters.session_id !== 'string' || !/^[a-zA-Z0-9_-]{1,128}$/.test(parameters.session_id))) throw new TypeError('Invalid session display locator.');
      return { endpoint: parameters.kind === 'threads' ? `/api/runtime/threads?${query}` : `/api/runtime/sessions/${parameters.session_id}/events?${query}` };
    }
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
    ...((request.appId === "storage" || action === "pwa.read_model") ? { _app_secret_request: { logical_names: [], required: false } } : {}),
  });
  if (body.length > 16_384) throw new TypeError("Read-model retry request exceeds its budget.");
  return { endpoint: `/api/apps/${request.appId}/backend`, body };
}
