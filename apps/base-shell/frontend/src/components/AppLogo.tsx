import { AppRegistryItem } from "../api";

function initials(name: string): string {
  return name
    .replace(/[^A-Za-z0-9]+/g, " ")
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase() || "A";
}

export function AppLogo({ app, className = "" }: { app: AppRegistryItem; className?: string }) {
  if (app.logo?.kind === "image" && app.logo.value) {
    return (
      <span className={`bs-app-logo is-image ${className}`}>
        <img alt="" loading="lazy" src={app.logo.value} />
      </span>
    );
  }
  return (
    <span className={`bs-app-logo is-glyph ${className}`}>
      <span>{app.logo?.value || initials(app.name || app.app_id)}</span>
    </span>
  );
}
