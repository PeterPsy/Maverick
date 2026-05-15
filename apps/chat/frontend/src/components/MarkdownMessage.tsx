import type { ComponentPropsWithoutRef, MouseEvent } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { openAppRouteInShell, openStoragePathInShell } from "../lib/shellNavigation";
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
  if (!storageTarget) {
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
