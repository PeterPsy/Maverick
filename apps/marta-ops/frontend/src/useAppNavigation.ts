import { useCallback, useEffect, useState } from "react";
import type { ViewId } from "./types";
import type { AdminFilter, DeliveryFilter } from "./navigation";
import { openApp, postToShell, viewFromAppPage } from "./lib/shellNavigation";
import { useViewState } from "./lib/viewState";

const EMPTY_QUERIES: Partial<Record<ViewId, string>> = {};
const DELIVERY_FILTERS = new Set([
  "open",
  "overdue",
  "approval",
  "all",
  "published",
]);
const ADMIN_FILTERS = new Set([
  "attention",
  "receivables",
  "all",
  "not_due",
  "to_invoice",
  "invoiced",
  "overdue",
  "paid",
]);

export function useAppNavigation(appId: string) {
  const [view, setView] = useState<ViewId>(
    () =>
      viewFromAppPage(
        new URLSearchParams(window.location.search).get("app_page"),
      ) || "today",
  );
  const [queries, setQueries] = useViewState("queries", EMPTY_QUERIES);
  const [deliveryFilter, setDeliveryFilter] = useViewState<DeliveryFilter>(
    "deliveries.filter",
    "open",
  );
  const [adminFilter, setAdminFilter] = useViewState<AdminFilter>(
    "admin.filter",
    "attention",
  );
  const [, setDeliveryWork] = useViewState("deliveries.workId", "");
  const navigate = useCallback(
    (next: ViewId) => {
      setView(next);
      openApp(appId, { app_page: next });
    },
    [appId],
  );
  const setQuery = useCallback(
    (query: string) => {
      const target = view === "today" ? "work" : view;
      if (view === "today") navigate(target);
      setQueries((current) => ({ ...current, [target]: query }));
    },
    [view, navigate, setQueries],
  );

  const applyParams = useCallback(
    (params: Record<string, unknown>) => {
      const next = viewFromAppPage(params.app_page);
      if (next) setView(next);
      if (
        typeof params.delivery_filter === "string" &&
        DELIVERY_FILTERS.has(params.delivery_filter)
      ) {
        setDeliveryFilter(params.delivery_filter as DeliveryFilter);
        if (params.reset_filters === true) {
          setDeliveryWork("");
          setQueries((current) => ({ ...current, deliveries: "" }));
        }
      }
      if (
        typeof params.admin_filter === "string" &&
        ADMIN_FILTERS.has(params.admin_filter)
      ) {
        setAdminFilter(params.admin_filter as AdminFilter);
        if (params.reset_filters === true)
          setQueries((current) => ({ ...current, admin: "" }));
      }
    },
    [setAdminFilter, setDeliveryFilter, setDeliveryWork, setQueries],
  );

  useEffect(() => {
    postToShell({
      type: "maverick.app.selection-changed",
      owner_app_id: appId,
      selection: {
        app_page: view,
        delivery_filter: deliveryFilter,
        admin_filter: adminFilter,
      },
    });
  }, [appId, view, deliveryFilter, adminFilter]);

  return {
    view,
    setView,
    query: queries[view] || "",
    setQuery,
    navigate,
    applyParams,
  };
}
