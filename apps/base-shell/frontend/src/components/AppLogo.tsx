import { AppRegistryItem } from "../api";

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
      <span aria-hidden="true" className="material-symbols-rounded">{app.logo?.value || defaultIcon(app)}</span>
    </span>
  );
}

function defaultIcon(app: AppRegistryItem): string {
  if (app.views.includes("chat")) {
    return "forum";
  }
  if (app.views.includes("agents")) {
    return "smart_toy";
  }
  if (app.views.includes("shell")) {
    return "dashboard";
  }
  return "apps";
}
