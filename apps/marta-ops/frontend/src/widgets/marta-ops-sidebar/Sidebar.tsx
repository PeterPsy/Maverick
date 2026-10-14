import { useMemo } from "react";
import { Icon } from "../../Icon";
import {
  mountedAppIdFromPath,
  openWidgetApp,
  postToShell,
  viewFromAppPage,
} from "../../lib/shellNavigation";
import { useShellTheme } from "../../lib/shellTheme";
import { QUICK_FILTERS, SECTIONS } from "../../navigation";
import { useSidebarContext } from "../useSidebarContext";
import { useSidebarSummary } from "../useSidebarSummary";

const WIDGET_ID = "marta-ops-sidebar";

function Badge({
  count,
  label,
  danger = false,
}: {
  count: number | undefined;
  label: string;
  danger?: boolean;
}) {
  if (count === undefined) return null;
  return (
    <span
      aria-label={`${count} ${label}`}
      className={`marta-sidebar-badge ${danger && count > 0 ? "is-danger" : ""}`}
    >
      {count}
    </span>
  );
}

export function MartaOpsSidebar() {
  useShellTheme();
  const appId = useMemo(() => mountedAppIdFromPath(), []);
  const {
    params,
    isMobile,
    error: contextError,
    retry,
  } = useSidebarContext(appId, WIDGET_ID);
  const { summary, error, refresh } = useSidebarSummary(appId);
  const activeView = viewFromAppPage(params.app_page) || "today";

  function navigate(next: Record<string, unknown>) {
    openWidgetApp(appId, next);
    if (isMobile) postToShell({ type: "loopino.shell.sidebar.close" });
  }

  return (
    <main
      className={`marta-sidebar-widget ${isMobile ? "is-shell-mobile" : ""}`}
    >
      <p className="marta-sidebar-heading">Marta Ops</p>
      <nav aria-label="Sezioni Marta Ops">
        {SECTIONS.map((section) => {
          const badge =
            section.id === "deliveries"
              ? {
                  count: summary?.overdue_deliveries,
                  label: "consegne in ritardo",
                  danger: true,
                }
              : section.id === "tasks"
                ? {
                    count: summary?.open_tasks,
                    label: "attività da fare",
                    danger: false,
                  }
                : section.id === "admin"
                  ? {
                      count: summary?.receivables,
                      label: "lavori da incassare",
                      danger: Boolean(summary?.overdue_payments),
                    }
                  : null;
          return (
            <button
              aria-current={activeView === section.id ? "page" : undefined}
              className={`marta-sidebar-row ${activeView === section.id ? "is-active" : ""}`}
              key={section.id}
              onClick={() => navigate({ app_page: section.id })}
              type="button"
            >
              <Icon name={section.icon} size={18} />
              <span className="marta-sidebar-row__label">{section.label}</span>
              {badge && <Badge {...badge} />}
            </button>
          );
        })}
      </nav>
      <p className="marta-sidebar-heading marta-sidebar-heading--filters">
        Filtri rapidi
      </p>
      <nav aria-label="Filtri rapidi">
        {QUICK_FILTERS.map((filter) => {
          const active =
            activeView === filter.view && params[filter.param] === filter.id;
          return (
            <button
              aria-pressed={active}
              className={`marta-sidebar-row marta-sidebar-row--filter ${active ? "is-active" : ""}`}
              key={filter.id}
              onClick={() =>
                navigate({
                  app_page: filter.view,
                  [filter.param]: filter.id,
                  reset_filters: true,
                })
              }
              type="button"
            >
              <span
                aria-hidden="true"
                className={`marta-sidebar-dot ${filter.id === "overdue" ? "is-danger" : ""}`}
              />
              <span className="marta-sidebar-row__label">{filter.label}</span>
              <Badge
                count={summary?.[filter.count]}
                label={filter.label.toLocaleLowerCase("it")}
                danger={filter.id === "overdue"}
              />
            </button>
          );
        })}
      </nav>
      {(contextError || error) && (
        <div className="marta-sidebar-feedback" role="status">
          <span>{contextError || error}</span>
          <button
            onClick={() => (contextError ? retry() : void refresh())}
            type="button"
          >
            Riprova
          </button>
        </div>
      )}
    </main>
  );
}
