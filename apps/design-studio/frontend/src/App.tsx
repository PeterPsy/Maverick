import { useEffect, useMemo, useState } from "react";
import { Download, FileInput, Loader2, Plus, RefreshCw, Search, ShieldCheck } from "lucide-react";
import { currentDesignStudioAppId, designStudioAction, loadDesignStudioStatus } from "./api";
import type { DesignProject, DesignStudioStatus } from "./types";
import "./styles/main.css";

type Notice = {
  kind: "ok" | "error";
  message: string;
};

export function App() {
  const appId = currentDesignStudioAppId();
  const [status, setStatus] = useState<DesignStudioStatus | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [query, setQuery] = useState("");
  const [name, setName] = useState("New interface direction");
  const [prompt, setPrompt] = useState("");
  const [storagePath, setStoragePath] = useState("storage/uploaded/");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busy, setBusy] = useState(false);

  const selectedProject = useMemo(
    () => status?.state.projects.find((project) => project.id === selectedId) || status?.state.projects[0] || null,
    [selectedId, status],
  );
  const filteredProjects = useMemo(() => {
    const text = query.trim().toLowerCase();
    const projects = status?.state.projects || [];
    if (!text) {
      return projects;
    }
    return projects.filter((project) =>
      `${project.name} ${project.prompt} ${project.source_files.join(" ")}`.toLowerCase().includes(text),
    );
  }, [query, status]);

  useEffect(() => {
    void refresh();
  }, []);

  async function refresh() {
    setBusy(true);
    try {
      const next = await loadDesignStudioStatus(appId);
      setStatus(next);
      setSelectedId(next.state.view_state.selected_project_id || next.state.projects[0]?.id || "");
      setNotice(null);
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Unable to load Design Studio." });
    } finally {
      setBusy(false);
    }
  }

  async function createProject() {
    await runAction("create_project", { name, prompt }, "Project created.");
  }

  async function importSource() {
    if (!selectedProject) {
      setNotice({ kind: "error", message: "Create or select a project before importing." });
      return;
    }
    await runAction(
      "import_from_storage",
      { project_id: selectedProject.id, workspace_relative_path: storagePath },
      "Storage source imported.",
    );
  }

  async function exportProject() {
    if (!selectedProject) {
      setNotice({ kind: "error", message: "Create or select a project before exporting." });
      return;
    }
    await runAction("export_to_storage", { project_id: selectedProject.id }, "Project exported to Storage.");
  }

  async function runAction(action: string, args: Record<string, unknown>, success: string) {
    setBusy(true);
    try {
      const result = await designStudioAction<{ state?: DesignStudioStatus["state"]; project?: DesignProject }>(appId, action, args);
      const next = await loadDesignStudioStatus(appId);
      setStatus(next);
      setSelectedId(result.project?.id || next.state.view_state.selected_project_id || next.state.projects[0]?.id || "");
      setNotice({ kind: "ok", message: success });
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Design Studio action failed." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="design-studio-root">
      <section className="design-studio-shell">
        <header className="design-studio-topbar">
          <div className="design-studio-title">
            <span className="design-studio-glyph">stylus_note</span>
            <div>
              <h1>Design Studio</h1>
              <p>OpenDesign {status?.opendesign.version || "0.10.1"} in Maverick sandbox</p>
            </div>
          </div>
          <label className="design-studio-search">
            <Search size={18} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search projects and Storage refs" />
          </label>
          <div className="design-studio-actions">
            <button className="secondary" type="button" onClick={refresh} disabled={busy}>
              {busy ? <Loader2 className="spin" size={17} /> : <RefreshCw size={17} />}
              <span>Refresh</span>
            </button>
            <button className="primary" type="button" onClick={createProject} disabled={busy}>
              <Plus size={17} />
              <span>Project</span>
            </button>
          </div>
        </header>

        <div className="design-studio-status">
          <StatusPill label="Sidecar" value={status ? "governed" : "loading"} />
          <StatusPill label="Provider" value="Maverick proxy" />
          <StatusPill label="Blocked" value={(status?.state.route_policy.blocked.length || 3).toString()} />
          <StatusPill label="Exports" value="Storage" />
        </div>

        {notice ? <div className={`design-studio-notice ${notice.kind}`}>{notice.message}</div> : null}

        <div className="design-studio-workspace">
          <aside className="design-studio-projects">
            <div className="design-studio-panel-head">
              <span>Projects</span>
              <small>{filteredProjects.length}</small>
            </div>
            <div className="design-studio-new">
              <input value={name} onChange={(event) => setName(event.target.value)} aria-label="Project name" />
              <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Design brief or generation prompt" />
            </div>
            <div className="design-studio-list">
              {filteredProjects.map((project) => (
                <button
                  className={`design-studio-row ${project.id === selectedProject?.id ? "active" : ""}`}
                  key={project.id}
                  type="button"
                  onClick={() => setSelectedId(project.id)}
                >
                  <span>{project.name}</span>
                  <small>{project.status}</small>
                </button>
              ))}
              {!filteredProjects.length ? <div className="design-studio-empty">No design projects</div> : null}
            </div>
          </aside>

          <section className="design-studio-detail">
            <div className="design-studio-detail-head">
              <div>
                <h2>{selectedProject?.name || "No project selected"}</h2>
                <p>{selectedProject?.id || "Create a project to start importing design sources."}</p>
              </div>
              <div className="design-studio-detail-actions">
                <button className="secondary" type="button" onClick={importSource} disabled={busy || !selectedProject}>
                  <FileInput size={17} />
                  <span>Import</span>
                </button>
                <button className="secondary" type="button" onClick={exportProject} disabled={busy || !selectedProject}>
                  <Download size={17} />
                  <span>Export</span>
                </button>
              </div>
            </div>

            <label className="design-studio-field">
              <span>Storage source</span>
              <input value={storagePath} onChange={(event) => setStoragePath(event.target.value)} />
            </label>

            <div className="design-studio-grid">
              <Metric label="Sources" value={selectedProject?.source_files.length || 0} />
              <Metric label="Imports" value={selectedProject?.imports.length || 0} />
              <Metric label="Exports" value={selectedProject?.exports.length || 0} />
              <Metric label="Status" value={selectedProject?.status || "idle"} />
            </div>

            <div className="design-studio-section">
              <h3>Storage References</h3>
              <div className="design-studio-reference-list">
                {(selectedProject?.source_files || []).map((item) => (
                  <code key={item}>{item}</code>
                ))}
                {!selectedProject?.source_files.length ? <span>No source files imported</span> : null}
              </div>
            </div>

            <div className="design-studio-section sidecar">
              <div className="design-studio-sidecar-head">
                <h3>OpenDesign Surface</h3>
                <span>
                  <ShieldCheck size={15} />
                  sandbox policy
                </span>
              </div>
              <iframe title="OpenDesign governed sidecar" src={status?.sidecar.proxy_url || `/api/apps/${appId}/sidecars/opendesign/`} />
            </div>
          </section>
        </div>
      </section>
    </main>
  );
}

function StatusPill({ label, value }: { label: string; value: string }) {
  return (
    <span className="design-studio-pill">
      <small>{label}</small>
      <strong>{value}</strong>
    </span>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="design-studio-metric">
      <small>{label}</small>
      <strong>{value}</strong>
    </div>
  );
}
