import { AccountAvatar } from "@maverick/account-avatar";
import type { SessionUser } from "../api";

export function UserAvatar({ user, className = "", size = 26 }: { user?: SessionUser | null; className?: string; size?: number }) {
  const name = user?.display_name || user?.email || user?.username || "Maverick";
  const initials = name.split(/[\s@._-]+/).filter(Boolean).slice(0, 2).map(part => part[0]).join("").toUpperCase();
  return <span className={`bs-user-avatar ${className}`} aria-hidden="true">
    <AccountAvatar pictureUrl={user?.avatar_url ?? undefined} size={size} fallback={initials} />
  </span>;
}
