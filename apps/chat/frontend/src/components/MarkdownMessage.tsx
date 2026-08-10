import type { ComponentPropsWithoutRef, MouseEvent } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { openAppParamsInShell, openAppRouteInShell, openStoragePathInShell, shellAppHrefTarget } from "../lib/shellNavigation";
import { storageAppPageShellHref, storageLinkTargetFromHref, storageShellHref } from "../lib/storageLinks";

export function MarkdownMessage({ content }: { content: string }) {
  return (
    <ReactMarkdown components={{ a: MarkdownLink }} rehypePlugins={[rehypeSanitize]} remarkPlugins={[remarkGfm]}>
      {content}
    </ReactMarkdown>
  );
}

function MarkdownLink({ children, href, onClick, ...props }: ComponentPropsWithoutRef<"a">) {
  const storageTarget = typeof href === "string" ? storageLinkTargetFromHref(href) : null;
  const shellAppTarget = storageTarget ? null : shellAppHrefTarget(href);
  if (!storageTarget) {
    if (isAbsoluteHttpUrl(href)) {
      return (
        <a {...props} href={href} onClick={onClick} rel={externalLinkRel(props.rel)} target="_blank">
          {children}
        </a>
      );
    }
    if (shellAppTarget) {
      const target = shellAppTarget;

      function handleShellAppClick(event: MouseEvent<HTMLAnchorElement>) {
        onClick?.(event);
        if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
          return;
        }
        if (openAppParamsInShell(target.appId, target.params)) {
          event.preventDefault();
        }
      }

      return (
        <a href={href} onClick={handleShellAppClick} {...props}>
          {children}
        </a>
      );
    }
    return (
      <a href={href} onClick={onClick} {...props}>
        {children}
      </a>
    );
  }
  const target = storageTarget;

  function handleClick(event: MouseEvent<HTMLAnchorElement>) {
    onClick?.(event);
    if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
      return;
    }
    event.preventDefault();
    if (target.kind === "workspace_path") {
      openStoragePathInShell(target.workspaceRelativePath);
    } else {
      openAppRouteInShell("storage", target.appPage);
    }
  }

  const shellHref =
    target.kind === "workspace_path" ? storageShellHref(target.workspaceRelativePath) : storageAppPageShellHref(target.appPage);

  return (
    <a href={shellHref} onClick={handleClick} {...props}>
      {children}
    </a>
  );
}

function isAbsoluteHttpUrl(value: unknown): value is string {
  if (typeof value !== "string" || !value.trim()) {
    return false;
  }
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function externalLinkRel(value: unknown): string {
  const relValues = new Set(
    typeof value === "string"
      ? value
          .split(/\s+/)
          .map((item) => item.trim())
          .filter(Boolean)
      : [],
  );
  relValues.add("noopener");
  relValues.add("noreferrer");
  return Array.from(relValues).join(" ");
}
