const STORAGE_PATH_PATTERN = /(?:^|\/)(storage\/(?:generated|uploaded)\/.+)$/;
const STORAGE_LINE_SUFFIX_PATTERN = /(\.[A-Za-z0-9]{1,12})(?::\d+){1,2}$/;
const URL_PARSE_BASE = "https://maverick.local";

export type StorageLinkTarget =
  | {
      kind: "app_page";
      appPage: string;
    }
  | {
      kind: "workspace_path";
      workspaceRelativePath: string;
    };

export function storageLinkTargetFromHref(href: string): StorageLinkTarget | null {
  const workspaceRelativePath = workspaceStoragePathFromTarget(href);
  if (workspaceRelativePath) {
    return { kind: "workspace_path", workspaceRelativePath };
  }
  const appPage = storageAppPageFromTarget(href);
  if (appPage) {
    return { kind: "app_page", appPage };
  }
  const queryPath = storageWorkspacePathFromQuery(href);
  if (queryPath) {
    return { kind: "workspace_path", workspaceRelativePath: queryPath };
  }
  return null;
}

export function workspaceStoragePathFromTarget(target: string): string {
  const cleaned = trimLinkTarget(target);
  if (!cleaned) {
    return "";
  }
  const path = decodePath(pathnameFromTarget(cleaned)).replace(/\\/g, "/");
  const match = path.match(STORAGE_PATH_PATTERN);
  if (!match) {
    return "";
  }
  const storagePath = stripLineSuffix(trimLinkTarget(match[1]));
  if (!isSafeStoragePath(storagePath)) {
    return "";
  }
  return storagePath;
}

export function storageShellHref(workspaceRelativePath: string): string {
  const path = workspaceRelativePath.trim();
  if (!path) {
    return "/app/storage";
  }
  const query = new URLSearchParams({ workspace_relative_path: path });
  return `/app/storage?${query.toString()}`;
}

export function storageAppPageShellHref(appPage: string): string {
  const page = appPage
    .split("/")
    .map((segment) => segment.trim())
    .filter(Boolean)
    .map(encodeURIComponent)
    .join("/");
  return page ? `/app/storage/${page}` : "/app/storage";
}

function pathnameFromTarget(target: string): string {
  try {
    return new URL(target, URL_PARSE_BASE).pathname;
  } catch {
    return target.split(/[?#]/, 1)[0];
  }
}

function storageAppPageFromTarget(target: string): string {
  const url = parseUrl(target);
  if (!url) {
    return "";
  }
  const segments = url.pathname.split("/").filter(Boolean).map(decodePath);
  const [routeKind, appId, ...pageSegments] = segments;
  if ((routeKind !== "app" && routeKind !== "apps") || appId !== "storage" || pageSegments.length === 0) {
    return "";
  }
  return pageSegments.join("/");
}

function storageWorkspacePathFromQuery(target: string): string {
  const url = parseUrl(target);
  if (!url) {
    return "";
  }
  const segments = url.pathname.split("/").filter(Boolean);
  if (segments[0] !== "app" || segments[1] !== "storage") {
    return "";
  }
  return workspaceStoragePathFromTarget(url.searchParams.get("workspace_relative_path") || url.searchParams.get("path") || "");
}

function parseUrl(target: string): URL | null {
  try {
    return new URL(trimLinkTarget(target), URL_PARSE_BASE);
  } catch {
    return null;
  }
}

function trimLinkTarget(value: string): string {
  return value.trim().replace(/[.,;:!?]+$/, "");
}

function decodePath(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function stripLineSuffix(value: string): string {
  return value.replace(STORAGE_LINE_SUFFIX_PATTERN, "$1");
}

function isSafeStoragePath(path: string): boolean {
  const segments = path.split("/");
  return (
    segments.length >= 3 &&
    segments[0] === "storage" &&
    (segments[1] === "generated" || segments[1] === "uploaded") &&
    segments.slice(2).every((segment) => Boolean(segment) && segment !== "." && segment !== "..")
  );
}
