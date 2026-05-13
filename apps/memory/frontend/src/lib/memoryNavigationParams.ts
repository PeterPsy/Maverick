export type MemoryNavigationParams = Record<string, string | boolean | null | undefined>;

export function scalarString(value: unknown): string {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

export function nodeIdFromParams(params: MemoryNavigationParams): string {
  const directNodeId = scalarString(params.node_id) || scalarString(params.entity_id) || scalarString(params.id);
  if (directNodeId) {
    return directNodeId;
  }
  const appPage = scalarString(params.app_page);
  const match = /^nodes\/([^/?#]+)$/.exec(appPage);
  if (!match?.[1]) {
    return "";
  }
  return decodeParam(match[1]);
}

export function shouldOpenCreateNode(params: MemoryNavigationParams): boolean {
  return params.new_node === true || scalarString(params.new_node) === "true" || scalarString(params.create_node) === "true";
}

export function shouldOpenPreviewContext(params: MemoryNavigationParams): boolean {
  return params.preview_context === true || scalarString(params.preview_context) === "true" || scalarString(params.context_preview) === "true";
}

function decodeParam(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}
