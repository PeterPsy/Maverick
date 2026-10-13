import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { listChatProjects, listProviders, type ChatProject, type ProviderItem } from "../../api/client";
import type { ScheduledConfig } from "../../api/scheduledChats";

export function ScheduledSettings({ initial, creating = false, busy, error, onClose, onSave }: {
  initial: ScheduledConfig; creating?: boolean; busy: boolean; error: string | null;
  onClose: (saved?: boolean) => void; onSave: (config: ScheduledConfig) => Promise<boolean>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [config, setConfig] = useState(initial);
  const [providers, setProviders] = useState<ProviderItem[]>([]);
  const [projects, setProjects] = useState<ChatProject[]>([]);
  useEffect(() => {
    dialog.current?.showModal();
    dialog.current?.querySelector<HTMLInputElement>("input")?.focus({ preventScroll: true });
    let cancelled = false;
    void Promise.allSettled([listProviders(), listChatProjects()]).then(results => {
      if (cancelled) return;
      if (results[0].status === "fulfilled") setProviders((results[0].value.items || []).filter(item => item.workspace_profile_binding_id && item.selectable !== false));
      if (results[1].status === "fulfilled") setProjects(results[1].value.projects);
    });
    return () => { cancelled = true; };
  }, []);
  const change = <K extends keyof ScheduledConfig>(key: K, value: ScheduledConfig[K]) => setConfig(current => ({ ...current, [key]: value }));
  const schedule = <K extends keyof ScheduledConfig["schedule"]>(key: K, value: ScheduledConfig["schedule"][K]) => setConfig(current => ({ ...current, schedule: { ...current.schedule, [key]: value } }));
  return <dialog className="scheduled-dialog" ref={dialog} onCancel={event => { event.preventDefault(); if (!busy) onClose(); }} aria-labelledby="scheduled-settings-title">
    <form onSubmit={event => {
      event.preventDefault();
      const final = creating ? { ...config, graph: { ...config.graph, nodes: config.graph.nodes.map((node, index) => index === 0 ? { ...node, instructions: config.instructions || node.instructions } : node) } } : config;
      void onSave(final).then(saved => { if (saved) onClose(true); });
    }}>
      <header><h2 id="scheduled-settings-title">{creating ? "New scheduled task" : "Schedule settings"}</h2><button className="scheduled-icon-button" aria-label="Close settings" disabled={busy} onClick={() => onClose()} type="button"><X size={18} /></button></header>
      <div className="scheduled-dialog__body">
        <label>Title<input disabled={busy} required maxLength={160} value={config.title} onChange={event => change("title", event.target.value)} /></label>
        <label>What should the agent do?<textarea disabled={busy} required={creating} rows={3} maxLength={8000} placeholder="A morning brief, a weekly review, something to keep an eye on…" value={config.instructions} onChange={event => change("instructions", event.target.value)} /></label>
        <fieldset disabled={busy}><legend>Frequency</legend>
          <label>Repeat<select aria-label="Repeat" value={config.schedule.frequency} onChange={event => schedule("frequency", event.target.value as ScheduledConfig["schedule"]["frequency"])}>
            <option value="daily">Every day</option><option value="weekdays">Weekdays</option><option value="weekly">Weekly</option><option value="once">Once</option><option value="manual">On demand</option>
          </select></label>
          {config.schedule.frequency === "weekly" && <label>Day<select value={config.schedule.weekday} onChange={event => schedule("weekday", Number(event.target.value))}>{["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map((day, index) => <option key={day} value={index}>{day}</option>)}</select></label>}
          {config.schedule.frequency === "once" && <label>Date<input type="date" required value={config.schedule.date} onChange={event => schedule("date", event.target.value)} /></label>}
          {config.schedule.frequency !== "manual" && <label>At<input type="time" required value={config.schedule.time} onChange={event => schedule("time", event.target.value)} /></label>}
          <label>Timezone<input required list="scheduled-timezones" value={config.schedule.timezone} onChange={event => schedule("timezone", event.target.value)} /><datalist id="scheduled-timezones">{["UTC", "Europe/Rome", "Europe/London", "America/New_York", "America/Los_Angeles", "Asia/Tokyo"].map(zone => <option key={zone} value={zone} />)}</datalist></label>
        </fieldset>
        <fieldset disabled={busy}><legend>Details</legend>
          <label>Model<select value={config.workspace_profile_binding_id} onChange={event => change("workspace_profile_binding_id", event.target.value)}><option value="">Workspace default</option>{config.workspace_profile_binding_id && !providers.some(p => p.workspace_profile_binding_id === config.workspace_profile_binding_id) && <option value={config.workspace_profile_binding_id}>Saved model selection</option>}{providers.map(provider => <option key={provider.provider_id} value={provider.workspace_profile_binding_id!}>{provider.label}</option>)}</select></label>
          <label>Reasoning<select value={config.reasoning_effort} onChange={event => change("reasoning_effort", event.target.value)}>{["", "low", "medium", "high", "xhigh", "max", "ultra"].map(effort => <option key={effort} value={effort}>{effort || "Model default"}</option>)}</select></label>
          <label>Project<select value={config.project_id} onChange={event => change("project_id", event.target.value)}><option value="">None</option>{projects.map(project => <option key={project.project_id} value={project.project_id}>{project.name}</option>)}</select></label>
          <label>Work chats<select value={config.conversation_mode} onChange={event => change("conversation_mode", event.target.value as "new" | "reuse")}><option value="new">New chats each run</option><option value="reuse">Reuse block chats</option></select></label>
          <label>Notifications<select value={String(config.notifications)} onChange={event => change("notifications", event.target.value === "true")}><option value="true">Checkpoints and results</option><option value="false">Off</option></select></label>
        </fieldset>
        <p className="scheduled-muted">Every block stops at a checkpoint. Confirm its result before the next blocks can start.</p>
        {error && <p className="scheduled-error" role="alert">{error}</p>}
      </div>
      <footer><button className="scheduled-button" disabled={busy} type="submit">{busy ? "Saving…" : creating ? "Create" : "Save changes"}</button></footer>
    </form>
  </dialog>;
}
