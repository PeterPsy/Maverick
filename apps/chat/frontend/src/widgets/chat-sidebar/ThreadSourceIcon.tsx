import { MessagesSquare, Monitor, Network, Palette, Radar, Telescope } from "lucide-react";
import type { ThreadSourceBadge } from "./sections";

const icons = {
  device_use: Monitor,
  multi_agent: Network,
  opendesign: Palette,
  research: Telescope,
  senses: Radar,
  source_app: MessagesSquare,
};

export function ThreadSourceIcon({ kind }: { kind: ThreadSourceBadge["kind"] }) {
  const Icon = icons[kind];
  return <Icon aria-hidden="true" size={13} strokeWidth={1.5} />;
}
