export type ToolActivityStatus = "started" | "updated" | "awaiting_confirmation" | "completed" | "failed";

export type StatusLabels = {
  active: string;
  completed: string;
  failed: string;
  waiting: string;
};

export function labelForStatus(status: ToolActivityStatus, labels: StatusLabels): string {
  if (status === "completed") return labels.completed;
  if (status === "failed") return labels.failed;
  if (status === "awaiting_confirmation") return labels.waiting;
  return labels.active;
}

export function statusLabels(active: string, completed: string, failed: string, waiting: string): StatusLabels {
  return { active, completed, failed, waiting };
}
