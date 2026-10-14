import { Layers, Pin } from "lucide-react";
import type { ActiveAppContext } from "../../lib/activeAppContext";

export function AppContextButton({ context, isPinned, onToggle }: {
  context: ActiveAppContext | null;
  isPinned: boolean;
  onToggle: () => void;
}) {
  const name = context?.name || "General";
  const params = context?.params ? Object.values(context.params).filter(Boolean).join(" · ") : "";
  return <button type="button" className="chat-floating-widget-shell__source-badge"
    aria-label={`${isPinned ? "Follow app context" : "Pin app context"}: ${name}`}
    aria-pressed={isPinned} disabled={!context}
    title={`${isPinned ? "Pinned context" : "Current context"}: ${name}${params ? ` · ${params}` : ""}`}
    onClick={onToggle}>
    <ContextIcon context={context} />
    {isPinned ? <Pin aria-hidden="true" className="chat-floating-context-pin" size={10} strokeWidth={2} /> : null}
  </button>;
}

function ContextIcon({ context }: { context: ActiveAppContext | null }) {
  const logo = context?.logo;
  if (logo?.kind === "image") {
    // Other apps' public icons live on the platform, outside Chat's isolated origin.
    const platformOrigin = (window as Window & { __MAVERICK_PLATFORM_ORIGIN__?: string }).__MAVERICK_PLATFORM_ORIGIN__;
    const url = new URL(logo.value, platformOrigin || window.location.origin).href;
    if (/\/apps\/[^/]+\/maverick-icon-compact\.png(?:[?#].*)?$/.test(url)) {
      const mask = `url(${JSON.stringify(url)}) center / contain no-repeat`;
      return <span aria-hidden="true" className="chat-floating-context-icon is-compact" style={{ mask, WebkitMask: mask }} />;
    }
    return <img alt="" className="chat-floating-context-icon" src={url} />;
  }
  if (logo?.kind === "glyph") {
    return <span aria-hidden="true" className="material-symbols-rounded chat-floating-context-icon">{logo.value}</span>;
  }
  return <Layers aria-hidden="true" className="chat-floating-context-icon" size={18} strokeWidth={1.5} />;
}
