import { requestJson } from "./http";

export type ScheduledBlock = {
  id: string;
  title: string;
  instructions: string;
  skill_ids: string[];
  position: { x: number; y: number };
};
export type ScheduledGraph = { nodes: ScheduledBlock[]; edges: { id: string; source: string; target: string }[] };
export type ChatSchedule = {
  frequency: "manual" | "once" | "daily" | "weekdays" | "weekly";
  timezone: string;
  time: string;
  weekday: number;
  date: string;
};
export type ScheduledConfig = {
  title: string;
  instructions: string;
  graph: ScheduledGraph;
  schedule: ChatSchedule;
  workspace_profile_binding_id: string;
  reasoning_effort: string;
  project_id: string;
  conversation_mode: "new" | "reuse";
  notifications: boolean;
};
export type ScheduledStep = {
  node_id: string;
  status: "pending" | "running" | "checkpoint" | "completed" | "failed" | "cancelled";
  session_id: string;
  turn_id: string;
  output: string;
  error: string;
};
export type ScheduledRun = { id: string; status: string; created_at: string; finished_at: string | null; steps: ScheduledStep[] };
export type ScheduledChat = ScheduledConfig & {
  id: string;
  revision: number;
  status: "active" | "paused" | "completed";
  next_run_at: string | null;
  chat_session_id: string;
  created_at: string;
  updated_at: string;
  run_status: string | null;
  run?: ScheduledRun | null;
  history?: Omit<ScheduledRun, "steps">[];
  message_status?: string | null;
  message_error?: string;
};
export type ScheduledChatSummary = Omit<ScheduledChat, "graph" | "run" | "history"> & { block_count?: number };

export function scheduledChatAction(action: string, fields: Record<string, unknown> = {}, signal?: AbortSignal) {
  return requestJson<{ chat?: ScheduledChat; chats?: ScheduledChatSummary[] }>("/api/apps/chat/backend", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...fields, action: `scheduled.${action}` }), signal,
  });
}

export function newScheduledConfig(title = "New scheduled chat", instructions = "Describe what the agent should do."): ScheduledConfig {
  return {
    title, instructions,
    graph: { nodes: [{ id: crypto.randomUUID(), title: "First checkpoint", instructions, skill_ids: [], position: { x: 120, y: 120 } }], edges: [] },
    schedule: { frequency: "daily", timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC", time: "09:00", weekday: 0, date: "" },
    workspace_profile_binding_id: "", reasoning_effort: "", project_id: "", conversation_mode: "new", notifications: true,
  };
}

export function scheduleLabel(schedule: ChatSchedule): string {
  const days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  const labels = { manual: "On demand", once: schedule.date, daily: "Every day", weekdays: "Weekdays", weekly: days[schedule.weekday] };
  return schedule.frequency === "manual" ? labels.manual : `${labels[schedule.frequency]} at ${schedule.time} · ${schedule.timezone}`;
}
