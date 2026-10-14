import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "./Icon";
import { AppContent } from "./components/AppContent";
import { AppTopbar, SectionNavigation } from "./components/AppNavigation";
import { useAppNavigation } from "./useAppNavigation";
import { useShellTheme } from "./lib/shellTheme";
import { ViewStateProvider } from "./lib/viewState";
import {
  isLoopinoParentMessage,
  mountedAppIdFromPath,
  postToShell,
} from "./lib/shellNavigation";
import {
  storageSelectionFromParams,
  type StorageSelection,
} from "./lib/storageSelection";
import { useRecordPanels } from "./useRecordPanels";
import { RecordPanels } from "./components/RecordPanels";
import { useMartaOps } from "./useMartaOps";

export function App() {
  return (
    <ViewStateProvider>
      <MartaOpsApp />
    </ViewStateProvider>
  );
}

function MartaOpsApp() {
  useShellTheme();
  const data = useMartaOps();
  const {
    state,
    loading,
    saving,
    error,
    clearError,
    integrate,
    mutate,
    refresh,
  } = data;
  const appId = useMemo(() => mountedAppIdFromPath(), []);
  const navigation = useAppNavigation(appId);
  const { view, setView, query, setQuery, navigate, applyParams } = navigation;
  const embedded =
    window.parent !== window ||
    Boolean(
      (window as Window & { __LOOPINO_PLATFORM_ORIGIN__?: string })
        .__LOOPINO_PLATFORM_ORIGIN__,
    );
  const [ideaCaptureRequest, setIdeaCaptureRequest] = useState(0);
  const controller = useRecordPanels();
  const { openWork, newWork, openContact, openTask } = controller;
  const requests = useRef(new Set<string>());
  const integrationRefreshStarted = useRef(false);
  const [pendingSelection, setPendingSelection] =
    useState<StorageSelection | null>(null);
  const handleStorageSelection = useCallback(
    (params: Record<string, unknown>) => {
      const selection = storageSelectionFromParams(params);
      if (!selection || requests.current.has(selection.requestKey)) return;
      requests.current.add(selection.requestKey);
      setView("work");
      void Promise.resolve(
        integrate({
          action: "link_storage_file",
          id: selection.workId,
          workspace_relative_path: selection.workspaceRelativePath,
        }),
      )
        .then(async () => {
          setPendingSelection(selection);
          await refresh();
        })
        .catch(() => {
          requests.current.delete(selection.requestKey);
        });
    },
    [integrate, refresh, setView],
  );
  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (!isLoopinoParentMessage(event)) return;
      const message = event.data as {
        app_id?: string;
        params?: Record<string, unknown>;
        type?: string;
      };
      if (
        message.type !== "loopino.app.navigate" ||
        (message.app_id && message.app_id !== appId)
      )
        return;
      const params = message.params || {};
      handleStorageSelection(params);
      applyParams(params);
      for (const [param, target] of [
        ["new_work", "work"],
        ["new_contact", "contacts"],
        ["new_task", "tasks"],
        ["new_idea", "ideas"],
      ] as const) {
        if (params[param] !== true) continue;
        const request = `${param}:${params[`${param}_request_id`] || "initial"}`;
        if (requests.current.has(request)) continue;
        requests.current.add(request);
        setView(target);
        if (param === "new_work") newWork();
        if (param === "new_contact") openContact(null);
        if (param === "new_task") openTask(null);
        if (param === "new_idea") setIdeaCaptureRequest((value) => value + 1);
      }
    }
    window.addEventListener("message", handleMessage);
    postToShell({ type: "loopino.app.ready", app_id: appId });
    const initialParams = Object.fromEntries(
      new URLSearchParams(window.location.search),
    );
    applyParams(initialParams);
    handleStorageSelection(initialParams);
    return () => window.removeEventListener("message", handleMessage);
  }, [
    appId,
    applyParams,
    handleStorageSelection,
    newWork,
    openContact,
    openTask,
    setView,
  ]);

  useEffect(() => {
    if (!ideaCaptureRequest || loading || view !== "ideas") return;
    document
      .querySelector<HTMLInputElement>('input[aria-label="Titolo idea"]')
      ?.focus();
    setIdeaCaptureRequest(0);
  }, [ideaCaptureRequest, loading, view]);

  useEffect(() => {
    if (!pendingSelection) return;
    const item = state.collaborations.find(
      (work) => work.id === pendingSelection.workId,
    );
    if (
      !item?.documents.some(
        (document) =>
          document.workspace_relative_path ===
          pendingSelection.workspaceRelativePath,
      )
    )
      return;
    if (
      !controller.panels.some(
        (panel) => panel.kind === "work" && panel.id === item.id,
      )
    )
      openWork(item);
    setPendingSelection(null);
  }, [controller.panels, openWork, pendingSelection, state.collaborations]);

  useEffect(() => {
    if (loading || saving || integrationRefreshStarted.current) return;
    const refreshedAt = Date.parse(state.integration_options.refreshed_at);
    const stale =
      !Number.isFinite(refreshedAt) ||
      Date.now() - refreshedAt > 6 * 60 * 60 * 1000;
    const incomplete =
      !state.integration_options.mail_provider_app_id ||
      !state.integration_options.calendar_provider_app_id ||
      !state.integration_options.storage_provider_app_id;
    if (!stale && !incomplete) return;
    integrationRefreshStarted.current = true;
    void Promise.resolve(integrate({ action: "refresh_integrations" })).catch(
      () => undefined,
    );
  }, [integrate, loading, saving, state.integration_options]);

  function createCurrent() {
    if (view === "contacts") openContact(null);
    else if (view === "tasks") openTask(null);
    else if (view === "ideas")
      document
        .querySelector<HTMLInputElement>('input[aria-label="Titolo idea"]')
        ?.focus();
    else newWork();
  }
  return (
    <div className={`marta-shell ${embedded ? "is-embedded" : ""}`}>
      <AppTopbar
        view={view}
        navigate={navigate}
        embedded={embedded}
        query={query}
        setQuery={setQuery}
        disabled={loading || saving}
        onCreate={createCurrent}
      />
      <main className="app-content">
        <AppContent
          data={data}
          controller={controller}
          navigation={navigation}
        />
      </main>
      {!embedded && (
        <SectionNavigation view={view} navigate={navigate} mobile />
      )}
      <RecordPanels
        appId={appId}
        controller={controller}
        state={state}
        saving={saving}
        mutate={mutate}
        integrate={integrate}
      />
      {error && (
        <div className="toast" role="alert">
          <span>{error}</span>
          <button
            aria-label="Chiudi messaggio"
            onClick={clearError}
            type="button"
          >
            <Icon name="close" size={16} />
          </button>
        </div>
      )}
    </div>
  );
}
