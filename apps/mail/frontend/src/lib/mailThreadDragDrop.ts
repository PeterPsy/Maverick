import type { MailAddress, MailThread } from '../api';

export const MAIL_THREAD_DRAG_DATA_TYPE = 'application/x-maverick-mail-thread';

export type MailThreadDragPayload = {
  connection_id: string;
  deep_link: string;
  last_message_at: string;
  owner_app_id: string;
  sender: string;
  snippet: string;
  subject: string;
  thread_id: string;
  unread: boolean;
};

type MailThreadDragDataTransfer = Pick<DataTransfer, 'setData'> & {
  effectAllowed?: DataTransfer['effectAllowed'];
};

export function mailThreadDragPayloadFromThread(
  thread: MailThread,
  ownerAppId = 'mail'
): MailThreadDragPayload {
  const sender = addressLabel(thread.participants[0]);
  const subject = thread.subject.trim() || 'Email thread';
  const snippet = thread.snippet.trim();
  return {
    connection_id: thread.connection_id,
    deep_link: `/app/${encodeURIComponent(ownerAppId)}?${new URLSearchParams({ thread: thread.id }).toString()}`,
    last_message_at: thread.last_message_at,
    owner_app_id: ownerAppId,
    sender,
    snippet: snippet || (sender ? `Mail thread from ${sender}` : 'Mail thread'),
    subject,
    thread_id: thread.id,
    unread: thread.unread
  };
}

export function writeMailThreadDragData(dataTransfer: MailThreadDragDataTransfer, payload: MailThreadDragPayload) {
  dataTransfer.setData(MAIL_THREAD_DRAG_DATA_TYPE, JSON.stringify(payload));
  dataTransfer.effectAllowed = 'copy';
}

function addressLabel(address?: MailAddress) {
  if (!address?.email) {
    return '';
  }
  return address.name ? `${address.name} <${address.email}>` : address.email;
}
