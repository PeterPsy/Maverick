import { describe, expect, it } from "vitest";
import { SCHEDULED_CHAT_DRAG_TYPE, scheduledChatDragData } from "./scheduledChatReferences";
import { hasAppReferenceDragData, appReferenceMentionItemsFromDataTransfer } from "./storageDragReferences";

function transfer(data: string) { return { types: [SCHEDULED_CHAT_DRAG_TYPE], getData: (type: string) => type === SCHEDULED_CHAT_DRAG_TYPE ? data : "" }; }
describe("scheduled task references", () => {
  it("uses the normal composer reference path with a stable graph identity", () => {
    const data = transfer(scheduledChatDragData({ id: "schedule-1", title: "Daily brief" }));
    expect(hasAppReferenceDragData(data)).toBe(true);
    expect(appReferenceMentionItemsFromDataTransfer(data)[0].reference).toMatchObject({
      app_id: "chat", entity_type: "scheduled_chat", entity_id: "schedule-1", deep_link: "/app/chat/scheduled/schedule-1",
    });
  });
  it("rejects forged owners, invalid ids, overlong labels and malformed transfers", () => {
    for (const value of ["{", JSON.stringify({ owner_app_id: "storage", id: "s", title: "Wrong" }),
      scheduledChatDragData({ id: "../schedule", title: "Wrong" }), scheduledChatDragData({ id: "s", title: "x".repeat(161) })]) {
      expect(appReferenceMentionItemsFromDataTransfer(transfer(value))).toEqual([]);
    }
  });
});
