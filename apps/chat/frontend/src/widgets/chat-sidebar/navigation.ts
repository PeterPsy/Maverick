import {
  Flame,
  Inbox,
  MessagesSquare,
  Monitor,
  Network,
  Palette,
  Radar,
  Telescope,
} from "lucide-react";
import type { NavGroupData } from "../../components/ui/dashboard-sidebar";
import type { ThreadFilter } from "./sections";

export function chatNavigationGroups(
  counts: Record<ThreadFilter, number>,
): NavGroupData[] {
  return [
    {
      heading: "Conversations",
      items: [
        {
          id: "all",
          title: "All conversations",
          icon: MessagesSquare,
          badge: counts.all,
        },
        {
          id: "hot",
          title: "Recent",
          icon: Flame,
          badge: counts.hot,
          description: "Latest 24 hours of activity",
        },
        {
          id: "unread",
          title: "Unread & active",
          icon: Inbox,
          badge: counts.unread,
        },
      ],
    },
    {
      heading: "Categories",
      items: [
        {
          id: "research",
          title: "Research",
          icon: Telescope,
          badge: counts.research,
        },
        {
          id: "multi_agent",
          title: "Multi-agent",
          icon: Network,
          badge: counts.multi_agent,
        },
        {
          id: "device_use",
          title: "Device Use",
          icon: Monitor,
          badge: counts.device_use,
        },
        { id: "senses", title: "Senses", icon: Radar, badge: counts.senses },
        {
          id: "opendesign",
          title: "OpenDesign",
          icon: Palette,
          badge: counts.opendesign,
        },
      ],
    },
  ];
}
