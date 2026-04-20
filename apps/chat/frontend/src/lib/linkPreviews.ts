import type { StructuredContent } from "../api/client";

type LinkCandidate = {
  label?: string;
  target: string;
};

const MARKDOWN_LINK_PATTERN = /\[([^\]]+)]\(([^)\s]+)(?:\s+"[^"]*")?\)/g;
const URL_PATTERN = /https?:\/\/[^\s<>)\]]+/g;
const WORKSPACE_STORAGE_PATTERN = /(?:^|[\s(["'`])((?:\/[\w.\-]+)*\/?storage\/(?:generated|uploaded)\/[^\s<>)\]"'`]+)/g;

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

function workspaceRelativePath(target: string): string {
  const cleaned = trimLinkTarget(target);
  let path = cleaned;
  try {
    const url = new URL(cleaned);
    path = url.pathname;
  } catch {
    path = cleaned;
  }

  const decoded = decodePath(path).replace(/\\/g, "/");
  const match = decoded.match(/(?:^|\/)(storage\/(?:generated|uploaded)\/.+)$/);
  return match ? trimLinkTarget(match[1]) : "";
}

function filenameFromPath(path: string): string {
  const name = path.split("/").filter(Boolean).at(-1) || path;
  return name.trim();
}

function safeTarget(candidateTarget: string, workspacePath: string): string {
  const target = trimLinkTarget(candidateTarget);
  if (/^https?:\/\//i.test(target)) {
    return target;
  }
  return workspacePath;
}

function linkCandidates(text: string): LinkCandidate[] {
  const candidates: LinkCandidate[] = [];
  for (const match of text.matchAll(MARKDOWN_LINK_PATTERN)) {
    candidates.push({ label: match[1].trim(), target: trimLinkTarget(match[2]) });
  }
  for (const match of text.matchAll(URL_PATTERN)) {
    candidates.push({ target: trimLinkTarget(match[0]) });
  }
  for (const match of text.matchAll(WORKSPACE_STORAGE_PATTERN)) {
    candidates.push({ target: trimLinkTarget(match[1]) });
  }
  return candidates;
}

export function structuredContentFromAgentLinks(text: string): StructuredContent[] {
  const seenPaths = new Set<string>();
  const items: StructuredContent[] = [];
  for (const candidate of linkCandidates(text)) {
    const path = workspaceRelativePath(candidate.target);
    if (!path || seenPaths.has(path)) {
      continue;
    }
    seenPaths.add(path);
    items.push({
      kind: "workspace.file.preview",
      payload: {
        source: "agent-link",
        label: candidate.label || filenameFromPath(path),
        target: safeTarget(candidate.target, path),
        workspace_relative_path: path,
      },
    });
  }
  return items;
}
