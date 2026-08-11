import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { LoaderCircle, Plus, Settings } from "lucide-react";
import { callDesignStudioBackend, mobileLayoutFromWidgetMessage, mountedAppId, projectIdFromWidgetMessage } from "../../backendApi";
import { applyInitialWidgetTheme, listenForWidgetTheme } from "../../widgetTheme";
import "../../styles/sidebar.css";

const WIDGET_ID = "design-studio-sidebar-footer";
const APP_ID = mountedAppId();

function publishPrimaryActionState() {
  window.parent?.postMessage(
    {
      type: "maverick.widget.primary-action.state",
      owner_app_id: APP_ID,
      widget_id: WIDGET_ID,
      available: true,
      label: "Nuovo progetto",
      preferred_surface: "sidebar",
    },
    window.location.origin,
  );
}

applyInitialWidgetTheme();
listenForWidgetTheme();

let isMobileLayout = false;

function DesignStudioSidebarFooter() {
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [projectId, setProjectId] = useState("");

  async function createProject() {
    if (creating) {
      return;
    }
    setCreating(true);
    setError("");
    try {
      const payload = await callDesignStudioBackend<{ od_project_id?: string; project?: { id?: string } }>("create_project", {
        name: "Untitled design",
      });
      const projectId = payload.od_project_id || payload.project?.id || "";
      if (!projectId) {
        throw new Error("OpenDesign did not return the new project.");
      }
      window.parent?.postMessage(
        { type: "maverick.widget.open-app", app_id: APP_ID, params: { od_project_id: projectId } },
        window.location.origin,
      );
      if (isMobileLayout) {
        window.parent?.postMessage({ type: "maverick.shell.sidebar.close" }, window.location.origin);
      }
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "Unable to create the project.");
    } finally {
      setCreating(false);
    }
  }

  useEffect(() => {
    publishPrimaryActionState();
    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || event.source !== window.parent || !event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as { owner_app_id?: string; type?: string; widget_id?: string };
      const selectedProjectId = projectIdFromWidgetMessage(event.data);
      if (selectedProjectId) {
        setProjectId(selectedProjectId);
      }
      const mobileLayout = mobileLayoutFromWidgetMessage(event.data);
      if (mobileLayout !== undefined) {
        isMobileLayout = mobileLayout;
      }
      if (payload.type === "maverick.widget.primary-action.query") {
        publishPrimaryActionState();
      }
      if (payload.type === "maverick.widget.primary-action.invoke" && payload.owner_app_id === APP_ID && payload.widget_id === WIDGET_ID) {
        void createProject();
      }
    }
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, []);

  function openSettings() {
    window.parent?.postMessage(
      {
        type: "maverick.widget.open-app",
        app_id: APP_ID,
        params: {
          ...(projectId ? { od_project_id: projectId } : {}),
          open_settings_request_id: crypto.randomUUID(),
        },
      },
      window.location.origin,
    );
  }

  return (
    <main className="ds-sidebar-footer">
      <div className="ds-sidebar-footer__actions">
      <button className="ds-sidebar-footer__primary" disabled={creating} onClick={() => void createProject()} type="button">
        {creating ? <LoaderCircle aria-hidden="true" className="spin" size={16} /> : <Plus aria-hidden="true" size={17} />}
        Nuovo progetto
      </button>
      <button aria-label="Impostazioni" className="ds-sidebar-footer__settings" onClick={openSettings} title="Impostazioni" type="button">
        <Settings aria-hidden="true" size={17} />
      </button>
      </div>
      {error ? <p role="alert">{error}</p> : null}
    </main>
  );
}

createRoot(document.getElementById("design-studio-sidebar-footer-root")!).render(<DesignStudioSidebarFooter />);
