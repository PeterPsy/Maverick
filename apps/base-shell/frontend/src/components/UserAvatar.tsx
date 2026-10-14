import { AccountAvatar } from "@loopino/account-avatar";
import type { CSSProperties } from "react";
import type { SessionUser } from "../api";

export function UserAvatar({ user, className = "", size = 26 }: { user?: SessionUser | null; className?: string; size?: number }) {
  const name = user?.display_name || user?.email || user?.username || "Loopino";
  const initials = name.split(/[\s@._-]+/).filter(Boolean).slice(0, 2).map(part => part[0]).join("").toUpperCase();
  return <span className={`bs-user-avatar ${className}`} style={{ "--bs-user-avatar-size": `${size}px` } as CSSProperties} aria-hidden="true">
    <AccountAvatar pictureUrl={user?.avatar_url ?? undefined} size="100%" fallback={initials} />
  </span>;
}
