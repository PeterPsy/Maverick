// Adapted from Atomic CRM deals/stages.ts and DealListContent.tsx.
// Copyright (c) 2024-present, Francois Zaninotto, Marmelab. MIT; see THIRD_PARTY_NOTICES.md.
import type { Collaboration, CollaborationPhase } from "../types";
import { PHASE_OPTIONS } from "../options";

export const CLOSED_PHASES = new Set<CollaborationPhase>(["completed", "lost"]);
export type WorkFilter = "open" | "all" | "closed";
export type Pipeline = Record<CollaborationPhase, Collaboration[]>;

export function groupByPhase(items: Collaboration[]): Pipeline {
  const columns = Object.fromEntries(
    PHASE_OPTIONS.map(([phase]) => [phase, [] as Collaboration[]]),
  ) as Pipeline;
  items.forEach((item) => columns[item.phase]?.push(item));
  PHASE_OPTIONS.forEach(([phase]) =>
    columns[phase].sort((a, b) => a.pipeline_order - b.pipeline_order),
  );
  return columns;
}

export function visibleWorks(
  items: Collaboration[],
  filter: WorkFilter,
  query: string,
  kind = "",
  phase = "",
) {
  const needle = query.trim().toLocaleLowerCase("it");
  return items.filter(
    (item) =>
      (filter === "all" ||
        (filter === "closed"
          ? CLOSED_PHASES.has(item.phase)
          : !CLOSED_PHASES.has(item.phase))) &&
      (!kind || item.kind === kind) &&
      (!phase || item.phase === phase) &&
      (!needle ||
        [
          item.title,
          item.partner,
          item.partner_email,
          item.next_action,
          item.notes,
        ].some((value) => value?.toLocaleLowerCase("it").includes(needle))),
  );
}

export function moveLocal(
  columns: Pipeline,
  id: string,
  phase: CollaborationPhase,
  index: number,
): Pipeline {
  const next = Object.fromEntries(
    PHASE_OPTIONS.map(([key]) => [
      key,
      columns[key].filter((item) => item.id !== id),
    ]),
  ) as Pipeline;
  const item = Object.values(columns)
    .flat()
    .find((work) => work.id === id);
  if (item) next[phase].splice(index, 0, { ...item, phase });
  return next;
}

export function beforeIdForMove(
  columns: Pipeline,
  id: string,
  phase: CollaborationPhase,
  index: number,
) {
  return columns[phase].filter((item) => item.id !== id)[index]?.id || "";
}
