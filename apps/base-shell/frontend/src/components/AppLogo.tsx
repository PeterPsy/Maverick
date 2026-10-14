import { AppRegistryItem } from "../api";

export function AppLogo({ app, className = "" }: { app: AppRegistryItem; className?: string }) {
  const logo = appLogoPresentation(app);
  if (logo.kind === "image") {
    // SDK compact assets are transparent silhouettes; native frames own their colour.
    if (/^\/apps\/[^/]+\/loopino-icon-compact\.png(?:[?#].*)?$/.test(logo.value)) {
      const mask = `url(${JSON.stringify(logo.value)}) center / contain no-repeat`;
      return (
        <span className={`bs-app-logo is-glyph ${className}`}>
          <span aria-hidden="true" className="bs-app-logo__compact" style={{
            width: "100%", height: "100%", backgroundColor: "currentColor",
            mask, WebkitMask: mask,
          }} />
        </span>
      );
    }
    return (
      <span className={`bs-app-logo is-image ${className}`}>
        <img alt="" loading="lazy" src={logo.value} />
      </span>
    );
  }
  return (
    <span className={`bs-app-logo is-glyph ${className}`}>
      <span aria-hidden="true" className="material-symbols-rounded">{logo.value}</span>
    </span>
  );
}

/** The same effective identity is used by the rail and contextual Chat. */
export function appLogoPresentation(app: AppRegistryItem): NonNullable<AppRegistryItem["logo"]> {
  return app.logo?.value ? app.logo : { kind: "glyph", value: defaultIcon(app) };
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
    "design-studio": "design_services",
    "docs-studio": "description",
    "document-generator": "description",
    "dynamic-views": "dashboard_customize",
    "fitness-coach": "fitness_center",
    mail: "mail",
    "marta-ops": "view_kanban",
    storage: "cloud",
    "gmail-app": "mail",
    "loopino-monitor": "monitor_heart",
    memory: "database",
    skills: "school",
    senses: "sensors",
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
