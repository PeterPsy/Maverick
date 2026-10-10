import type { ReactNode } from "react";
import type {
  CalendarConnection,
  CalendarRemoteCalendar,
  CalendarSourceOption,
  ColorClasses,
  DraftEvent,
  Event,
} from "./calendar-types";
export type EventPanelProps = {
  mode: "create" | "details";
  draft: DraftEvent | Event | null;
  error: string;
  isSaving: boolean;
  canSave: boolean;
  hasChanges?: boolean;
  categories: string[];
  colors: { name: string; value: string; bg: string; text: string }[];
  availableTags: string[];
  calendars?: CalendarRemoteCalendar[];
  connections?: CalendarConnection[];
  calendarSourceOptions?: CalendarSourceOption[];
  getColorClasses: (color: string) => ColorClasses;
  setDraft: (patch: DraftEvent) => void;
  toggleTag: (tag: string) => void;
  onCreate: () => void;
  onUpdate: () => void;
  onDelete: () => void;
  onClose: () => void;
  onCancelEdit?: () => void;
  children?: ReactNode;
};
