import type { NodeType } from "./types";

export const colors: Record<string, string> = {
  note: "#d8f06e",
  fact: "#67d5ff",
  decision: "#ffce73",
  file_ref: "#a68cff",
  app_entity_ref: "#ff8da1",
  person_ref: "#7cf0c6",
  company_ref: "#f4a261",
  project_ref: "#8fd3ff",
  topic: "#b8f48f",
  question: "#f497d1",
};

export const nodeTypes: NodeType[] = [
  "note",
  "fact",
  "decision",
  "file_ref",
  "app_entity_ref",
  "person_ref",
  "company_ref",
  "project_ref",
  "topic",
  "question",
];
