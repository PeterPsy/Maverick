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
  const iconByAppId: Record<string, string> = {
    agents: "smart_toy",
    "app-store": "storefront",
    "base-shell": "dashboard",
    browser: "language",
    calendar: "calendar_month",
    chat: "forum",
    checklist: "checklist",
    crm: "contacts",
    "developer-kit": "developer_board",
    "docs-studio": "description",
    "document-generator": "description",
    "dynamic-views": "dashboard_customize",
    "fitness-coach": "fitness_center",
    mail: "mail",
    storage: "cloud",
    "gmail-app": "mail",
    "maverick-monitor": "monitor_heart",
    memory: "database",
    skills: "school",
    speech: "record_voice_over",
    "settings": "admin_panel_settings",
    vault: "key",
    "website-studio": "web_asset",
  };
  if (iconByAppId[app.app_id]) {
    return iconByAppId[app.app_id];
  }
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
