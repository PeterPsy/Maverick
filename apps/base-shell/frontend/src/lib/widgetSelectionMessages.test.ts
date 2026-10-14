import { describe, expect, it } from "vitest";
import { widgetSelectionChangedMessage } from "./widgetSelectionMessages";

describe("widget selection messages", () => {
  it("forwards app-owned active selections only to widgets owned by the same app", () => {
    expect(
      widgetSelectionChangedMessage(
        {
          type: "loopino.app.selection-changed",
          owner_app_id: "agents",
          selection: { agent_type_id: "agent-type-a" },
        },
        "agents",
      ),
    ).toEqual({
      type: "loopino.app.selection-changed",
      owner_app_id: "agents",
      selection: { agent_type_id: "agent-type-a" },
    });
  });

  it("blocks selections from other app owners", () => {
    expect(
      widgetSelectionChangedMessage(
        {
          type: "loopino.app.selection-changed",
          owner_app_id: "chat",
          selection: { thread_id: "thread-a" },
        },
        "agents",
      ),
    ).toBeNull();
    expect(widgetSelectionChangedMessage({ type: "loopino.widget.data-changed", owner_app_id: "agents" }, "agents")).toBeNull();
  });
});
