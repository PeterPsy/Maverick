import { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Search } from "lucide-react";
import { callDesignStudioBackend, mobileLayoutFromWidgetMessage, mountedAppId, projectCreatedAt, projectIdFromWidgetMessage } from "../../backendApi";
import { applyInitialWidgetTheme, listenForWidgetTheme } from "../../widgetTheme";
import "../../styles/sidebar.css";

type OpenDesignProject = {
  id: string;
  name?: string;
  createdAt?: number | string;
  created_at?: number | string;
  updatedAt?: number | string;
  updated_at?: number | string;
};

applyInitialWidgetTheme();
listenForWidgetTheme();

let isMobileLayout = false;
const APP_ID = mountedAppId();

function DesignStudioSidebar() {
  const [projects, setProjects] = useState<OpenDesignProject[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const visibleProjects = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return projects
      .filter((project) => !needle || `${project.name || ""} ${project.id}`.toLocaleLowerCase().includes(needle))
      .sort((left, right) => projectCreatedAt(right) - projectCreatedAt(left));
  }, [projects, query]);

  async function refresh() {
    try {
      const payload = await callDesignStudioBackend<{ projects?: OpenDesignProject[] }>("list_projects");
      setProjects((payload.projects || []).filter((project) => project && typeof project.id === "string"));
      setError("");
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load OpenDesign projects.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || event.source !== window.parent) {
        return;
      }
      const projectId = projectIdFromWidgetMessage(event.data);
      if (projectId) {
        setSelectedProjectId(projectId);
      }
      const mobileLayout = mobileLayoutFromWidgetMessage(event.data);
      if (mobileLayout !== undefined) {
        isMobileLayout = mobileLayout;
      }
      const payload = event.data as { owner_app_id?: string; resource?: string; type?: string };
      if (payload.type === "maverick.widget.data-changed" && payload.owner_app_id === APP_ID) {
        void refresh();
      }
    }
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, []);

  function openProject(projectId: string) {
    setSelectedProjectId(projectId);
    window.parent?.postMessage(
      { type: "maverick.widget.open-app", app_id: APP_ID, params: { od_project_id: projectId } },
      window.location.origin,
    );
    if (isMobileLayout) {
      window.parent?.postMessage({ type: "maverick.shell.sidebar.close" }, window.location.origin);
    }
  }

  return (
    <main className="ds-sidebar">
      <label className="ds-sidebar__search">
        <Search aria-hidden="true" size={16} />
        <input aria-label="Search OpenDesign projects" onChange={(event) => setQuery(event.target.value)} placeholder="Search projects" value={query} />
      </label>
      <div className="ds-sidebar__list">
        {loading ? (
          <div aria-label="Loading OpenDesign projects" className="ds-sidebar__skeleton" role="status">
            <span /><span /><span />
          </div>
        ) : error ? (
          <button className="ds-sidebar__state" onClick={() => void refresh()} type="button">{error} Retry</button>
        ) : visibleProjects.length ? (
          visibleProjects.map((project) => (
            <button
              aria-current={selectedProjectId === project.id ? "page" : undefined}
              className={`ds-sidebar__project ${selectedProjectId === project.id ? "is-active" : ""}`}
              key={project.id}
              onClick={() => openProject(project.id)}
              type="button"
            >
              <span aria-hidden="true" className="material-symbols-rounded">design_services</span>
              <span className="ds-sidebar__project-copy">
                <strong>{project.name || "Untitled design"}</strong>
                <small>{formatUpdatedAt(projectUpdatedAt(project))}</small>
              </span>
            </button>
          ))
        ) : (
          <p className="ds-sidebar__state">{query ? "No projects match your search." : "No OpenDesign projects yet."}</p>
        )}
      </div>
    </main>
  );
}

function projectUpdatedAt(project: OpenDesignProject): number {
  const value = project.updatedAt ?? project.updated_at ?? 0;
  if (typeof value === "number") {
    return value;
  }
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatUpdatedAt(value: number): string {
  if (!value) {
    return "OpenDesign project";
  }
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(value));
}

createRoot(document.getElementById("design-studio-sidebar-root")!).render(<DesignStudioSidebar />);
