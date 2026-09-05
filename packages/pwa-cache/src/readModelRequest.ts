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
