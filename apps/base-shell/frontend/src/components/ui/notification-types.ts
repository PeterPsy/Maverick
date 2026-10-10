import type * as React from "react";

export interface NotificationAction {
  id?: string;
  label: string;
  done?: string;
}
export interface NotificationBase {
  id: string;
  app: string;
  title: string;
  body?: string;
  time?: string;
  accent?: string;
  icon?: React.ReactNode;
  read?: boolean;
  readable?: boolean;
  pending?: boolean;
  done?: string;
  actions?: NotificationAction[];
}
export type GenericNotification = NotificationBase & { kind: "generic" };
export type MessageNotification = NotificationBase & {
  kind: "message";
  from: string;
  text: string;
};
export type DeliveryNotification = NotificationBase & {
  kind: "delivery";
  steps: string[];
  step: number;
};
export type RideNotification = NotificationBase & {
  kind: "ride";
  minutes: number;
  vehicle: string;
  plate: string;
};
export type PaymentNotification = NotificationBase & {
  kind: "payment";
  amount: number;
  currency?: string;
  locale?: string;
};
export type CalendarNotification = NotificationBase & {
  kind: "calendar";
  date: string;
  attendees?: string[];
  locale?: string;
};
export type CodeNotification = NotificationBase & {
  kind: "code";
  code: string;
  expiresIn?: number;
  expiresAt?: string;
};
export type FlightNotification = NotificationBase & {
  kind: "flight";
  from: string;
  to: string;
  gate: string;
  previousGate?: string;
};
export type FitnessNotification = NotificationBase & {
  kind: "fitness";
  value: number;
  goal: number;
  unit: string;
  streak?: number;
  locale?: string;
};
export type LiveNotification =
  | GenericNotification
  | MessageNotification
  | DeliveryNotification
  | RideNotification
  | PaymentNotification
  | CalendarNotification
  | CodeNotification
  | FlightNotification
  | FitnessNotification;
export type NotificationKind = LiveNotification["kind"];

export interface LiveNotificationFeedProps extends Omit<
  React.ComponentProps<"div">,
  "onError"
> {
  /** Oldest first; notifications arriving later are appended and appear on top. */
  items: LiveNotification[];
  title?: string;
  autoplay?: boolean;
  initial?: number;
  interval?: number;
  loop?: boolean;
  height?: string;
  /** App backends own read/done/dismiss state; do not optimistically hide failures. */
  managed?: boolean;
  unreadCount?: number;
  onOpen?: (id: string) => void;
  onReadAll?: () => void | Promise<void>;
  onClear?: () => void | Promise<void>;
  onAction?: (
    id: string,
    label: string,
    actionId?: string,
  ) => void | Promise<void>;
  onDismiss?: (id: string) => void | Promise<void>;
  onError?: (error: unknown) => void;
}
export interface Entry {
  id: string;
  key: string;
  play: number;
  fresh: boolean;
  leaving: boolean;
  arrived: boolean;
  delay: number;
  leaveDelay: number;
}
export type StoryProps = { play: number; delay: number; reduced: boolean };
