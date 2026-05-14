import type { StorageViewFilter } from '../types';

const DATA_CHANGED_TYPE = 'maverick.app.data-changed';
const WIDGET_DATA_CHANGED_TYPE = 'maverick.widget.data-changed';
const VIEW_STATE_RESOURCE = 'view-state';

type RecordPayload = Record<string, unknown>;

export type StorageViewFilterChangedMessage = {
  detail: {
    view_filter: StorageViewFilter;
  };
  owner_app_id: string;
  resource: typeof VIEW_STATE_RESOURCE;
  type: typeof DATA_CHANGED_TYPE;
};

function isRecord(value: unknown): value is RecordPayload {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

export function storageViewFilterChangedMessage(ownerAppId: string, viewFilter: StorageViewFilter): StorageViewFilterChangedMessage {
  return {
    detail: {
      view_filter: viewFilter,
    },
    owner_app_id: ownerAppId,
    resource: VIEW_STATE_RESOURCE,
    type: DATA_CHANGED_TYPE,
  };
}

export function storageViewFilterFromMessage(message: unknown, ownerAppId: string): Partial<StorageViewFilter> | null {
  if (!isRecord(message)) {
    return null;
  }
  if (
    (message.type !== DATA_CHANGED_TYPE && message.type !== WIDGET_DATA_CHANGED_TYPE)
    || message.owner_app_id !== ownerAppId
    || message.resource !== VIEW_STATE_RESOURCE
  ) {
    return null;
  }
  if (!isRecord(message.detail) || !isRecord(message.detail.view_filter)) {
    return null;
  }
  return message.detail.view_filter as Partial<StorageViewFilter>;
}
