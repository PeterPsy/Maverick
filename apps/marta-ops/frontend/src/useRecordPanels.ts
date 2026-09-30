import { useCallback, useRef, useState } from "react";
import type {
  Collaboration,
  CollaborationPhase,
  Contact,
  Task,
  TaskDraft,
  WorkDraft,
} from "./types";

export type RecordPanel = { key: number } & (
  | { kind: "work"; id: string | null; preset: Partial<WorkDraft> }
  | { kind: "contact"; id: string | null }
  | { kind: "task"; id: string | null; preset: Partial<TaskDraft> }
);

export function useRecordPanels() {
  const [panels, setPanels] = useState<RecordPanel[]>([]);
  const sequence = useRef(0);
  const openWork = useCallback(
    (item: Collaboration | null, preset: Partial<WorkDraft> = {}) => {
      const panel: RecordPanel = {
        kind: "work",
        id: item?.id || null,
        preset,
        key: ++sequence.current,
      };
      setPanels((current) => [...current, panel]);
    },
    [],
  );
  const newWork = useCallback(
    (phase?: CollaborationPhase, contact?: Contact | null) => {
      openWork(null, {
        ...(phase ? { phase } : {}),
        ...(contact
          ? {
              contact_id: contact.id,
              partner: contact.company || contact.name,
              partner_email: contact.email,
            }
          : {}),
      });
    },
    [openWork],
  );
  const openContact = useCallback((item: Contact | null) => {
    const panel: RecordPanel = {
      kind: "contact",
      id: item?.id || null,
      key: ++sequence.current,
    };
    setPanels((current) => [...current, panel]);
  }, []);
  const openTask = useCallback(
    (item: Task | null, preset: Partial<TaskDraft> = {}) => {
      const panel: RecordPanel = {
        kind: "task",
        id: item?.id || null,
        preset,
        key: ++sequence.current,
      };
      setPanels((current) => [...current, panel]);
    },
    [],
  );
  const closePanel = useCallback(
    () => setPanels((current) => current.slice(0, -1)),
    [],
  );
  return { panels, openWork, newWork, openContact, openTask, closePanel };
}
