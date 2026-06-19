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

export function mountMailThreadDragPreview(thread: MailThread): HTMLElement | null {
  if (typeof document === 'undefined' || !document.body) {
    return null;
  }
  const preview = document.createElement('div');
  preview.className = 'mail-thread-drag-preview';
  preview.setAttribute('aria-hidden', 'true');

  const icon = document.createElement('span');
  icon.className = 'mail-thread-drag-preview__icon';
  icon.append(mailIconSvg());

  const title = document.createElement('span');
  title.className = 'mail-thread-drag-preview__title';
  title.textContent = thread.subject.trim() || 'Email thread';

  preview.append(icon, title);
  document.body.append(preview);
  return preview;
}

function mailIconSvg() {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.9');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');

  const outline = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  outline.setAttribute('d', 'M4 6h16v12H4z');
  const flap = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  flap.setAttribute('d', 'm4 7 8 6 8-6');

  svg.append(outline, flap);
  return svg;
}

function addressLabel(address?: MailAddress) {
  if (!address?.email) {
    return '';
  }
  return address.name ? `${address.name} <${address.email}>` : address.email;
}
