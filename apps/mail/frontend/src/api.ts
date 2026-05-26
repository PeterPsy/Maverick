export type MailAddress = {
  name?: string;
  email: string;
};

export type MailConnection = {
  id: string;
  provider: string;
  email_address: string;
  display_name: string;
  status: string;
  scopes?: string[];
};

export type MailProviderState = {
  provider: string;
  connected: boolean;
  configured: boolean;
  status: string;
};

export type MailThread = {
  id: string;
  connection_id: string;
  subject: string;
  participants: MailAddress[];
  last_message_at: string;
  snippet: string;
  unread: boolean;
  starred: boolean;
  labels: string[];
  messages?: MailMessage[];
};

export type MailMessage = {
  id: string;
  thread_id: string;
  sender: MailAddress;
  recipients: MailAddress[];
  sent_at: string;
  body_text: string;
  has_attachments: boolean;
};

export type MailDraft = {
  id: string;
  connection_id: string;
  thread_id?: string;
  subject: string;
  body_text: string;
  to: MailAddress[];
  cc?: MailAddress[];
  bcc?: MailAddress[];
  status: string;
};

export type MailStatus = {
  status?: string;
  mode?: string;
  connection_count?: number;
  unread_count?: number;
  draft_count?: number;
  health_status?: string;
};

export const MAIL_BACKEND_ACTIONS = {
  status: 'status',
  connectionsList: 'connections.list',
  connectionsStartOAuth: 'connections.start_oauth',
  connectionsCompleteOAuth: 'connections.complete_oauth',
  connectionsDisconnect: 'connections.disconnect',
  threadsList: 'threads.list',
  threadsGet: 'threads.get',
  threadsSync: 'threads.sync',
  draftsCreate: 'drafts.create',
  draftsSend: 'drafts.send',
  messagesMarkRead: 'messages.mark_read',
  labelsModify: 'labels.modify'
} as const;

export async function callBackend<T>(body: Record<string, unknown>): Promise<T> {
  const response = await fetch('/api/apps/mail/backend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const payload = (await response.json()) as T & { error?: string; detail?: string };
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || `Backend request failed with ${response.status}`);
  }
  return payload;
}
