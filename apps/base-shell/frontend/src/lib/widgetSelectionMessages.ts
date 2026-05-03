export type WidgetSelectionPayload = {
  owner_app_id?: string;
  selection?: Record<string, string | boolean | null>;
  type?: string;
};

export function widgetSelectionChangedMessage(payload: WidgetSelectionPayload, ownerAppId: string | undefined) {
  if (!ownerAppId || payload.type !== "maverick.app.selection-changed" || payload.owner_app_id !== ownerAppId) {
    return null;
  }
  return {
    type: "maverick.app.selection-changed",
    owner_app_id: payload.owner_app_id,
    selection: payload.selection || {},
  };
}
