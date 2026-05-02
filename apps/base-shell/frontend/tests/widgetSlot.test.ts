import { describe, expect, it } from "vitest";
import type { WidgetRegistryItem } from "../src/api";
import { selectPreferredWidget } from "../src/components/WidgetSlot";

function widget(ownerAppId: string, widgetId: string): WidgetRegistryItem {
  return {
    actions: {},
    content_kinds: ["shell.sidebar.primary"],
    frontend_mount: `/api/apps/widgets/${ownerAppId}/${widgetId}/frontend/`,
    host: "base-shell",
    owner_app_id: ownerAppId,
    widget_id: widgetId,
  };
}

describe("WidgetSlot selection", () => {
  it("prefers the active app owner when requested", () => {
    expect(selectPreferredWidget([widget("chat", "chat-sidebar"), widget("memory", "memory-sidebar")], "memory")).toEqual(
      expect.objectContaining({ owner_app_id: "memory", widget_id: "memory-sidebar" }),
    );
  });

  it("keeps preferred-owner slots empty when the active app has no widget", () => {
    expect(selectPreferredWidget([widget("chat", "chat-sidebar")], "memory")).toBeNull();
  });

  it("keeps registry order for slots without an active-owner preference", () => {
    expect(selectPreferredWidget([widget("chat", "chat-sidebar"), widget("memory", "memory-sidebar")], null)).toEqual(
      expect.objectContaining({ owner_app_id: "chat", widget_id: "chat-sidebar" }),
    );
  });
});
