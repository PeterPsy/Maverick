import type { IconName } from "./Icon";
import type { PaymentStatus, ViewId } from "./types";

export const SECTIONS: Array<{
  id: ViewId;
  label: string;
  icon: IconName;
}> = [
  { id: "today", label: "Oggi", icon: "today" },
  { id: "work", label: "Lavori", icon: "work" },
  {
    id: "deliveries",
    label: "Consegne",
    icon: "deliveries",
  },
  {
    id: "contacts",
    label: "Contatti",
    icon: "contacts",
  },
  {
    id: "tasks",
    label: "Attività",
    icon: "tasks",
  },
  {
    id: "admin",
    label: "Amministrazione",
    icon: "admin",
  },
  { id: "ideas", label: "Idee", icon: "ideas" },
];

export type DeliveryFilter =
  | "open"
  | "overdue"
  | "approval"
  | "all"
  | "published";
export type AdminFilter = "attention" | "receivables" | "all" | PaymentStatus;

export const QUICK_FILTERS = [
  {
    id: "overdue",
    label: "In ritardo",
    view: "deliveries",
    param: "delivery_filter",
    count: "overdue_deliveries",
  },
  {
    id: "approval",
    label: "Da approvare",
    view: "deliveries",
    param: "delivery_filter",
    count: "approvals",
  },
  {
    id: "receivables",
    label: "Da incassare",
    view: "admin",
    param: "admin_filter",
    count: "receivables",
  },
] as const;

export function createAction(view: ViewId) {
  if (view === "contacts")
    return { label: "Nuovo contatto", view, param: "new_contact" };
  if (view === "tasks")
    return { label: "Nuova attività", view, param: "new_task" };
  if (view === "ideas") return { label: "Nuova idea", view, param: "new_idea" };
  return { label: "Nuovo lavoro", view: "work" as const, param: "new_work" };
}
