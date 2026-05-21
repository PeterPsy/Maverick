import type { MentionItem } from "./mentions";

export type ExternalMentionDrop = {
  items: MentionItem[];
  requestId: string;
};

export type ExternalFileDrop = {
  files: File[];
  requestId: string;
};
