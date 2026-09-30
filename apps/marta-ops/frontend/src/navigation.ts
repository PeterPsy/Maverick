import type { IconName } from "./Icon";
import type { ViewId } from "./types";

export const SECTIONS: Array<{
  id: ViewId;
  label: string;
  icon: IconName;
  note: string;
}> = [
  { id: "today", label: "Oggi", icon: "today", note: "Priorità e scadenze" },
  { id: "work", label: "Lavori", icon: "work", note: "Pipeline e consegne" },
  {
    id: "contacts",
    label: "Contatti",
    icon: "contacts",
    note: "Brand, agenzie e persone",
  },
  {
    id: "tasks",
    label: "Attività",
    icon: "tasks",
    note: "Follow-up e promemoria",
  },
  { id: "ideas", label: "Idee", icon: "ideas", note: "Inbox creativa" },
];
