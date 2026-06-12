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
  settings?: Record<string, unknown>;
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
  cc?: MailAddress[];
  bcc?: MailAddress[];
  sent_at: string;
  body_text: string;
  body_html_sanitized?: string;
  body_html_gmail_sanitized?: string;
  body_html_rendered?: string;
  body_html_original_available?: boolean;
  body_html_original_size?: number;
  render_policy?: Record<string, unknown>;
  body_render_mode?: 'html' | 'plain';
  body_preview?: string;
  body_truncated?: boolean;
  body_source_truncated?: boolean;
  body_text_truncated?: boolean;
  body_html_truncated?: boolean;
  has_attachments: boolean;
  attachments?: MailAttachment[];
  inline_assets?: MailInlineAsset[];
};

export type MailAttachment = {
  id: string;
  filename: string;
  content_type?: string;
  size_bytes?: number;
  storage_state?: string;
};

export type MailInlineAsset = {
  content_id?: string;
  provider_attachment_id?: string;
  attachment_id?: string;
  message_id?: string;
  filename?: string;
  content_type?: string;
  size_bytes?: number;
};

export type MailAttachmentFetch = {
  attachment_id: string;
  status: 'metadata_only' | 'limit_required' | 'too_large' | 'invalid_payload' | 'saved' | 'fetched' | string;
  filename?: string;
  content_type?: string;
  size_bytes?: number;
  storage_state?: string;
  storage_ref?: Record<string, unknown>;
  data_base64url?: string;
  max_bytes?: number;
  detail?: string;
};

export type MailAttachmentFetchResponse = {
  attachment: MailAttachment;
  fetch: MailAttachmentFetch;
};

export type MailDraft = {
  id: string;
  connection_id: string;
  thread_id?: string;
  subject: string;
  body_text: string;
  body_html?: string;
  to: MailAddress[];
  cc?: MailAddress[];
  bcc?: MailAddress[];
  reply_to?: MailAddress[];
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
  connectionsPrepareImapSmtp: 'connections.prepare_imap_smtp',
  connectionsTestImapSmtp: 'connections.test_imap_smtp',
  connectionsActivateImapSmtp: 'connections.activate_imap_smtp',
  connectionsUpdateImapSmtp: 'connections.update_imap_smtp',
  connectionsDisconnect: 'connections.disconnect',
  mailboxesCounts: 'mailboxes.counts',
  threadsList: 'threads.list',
  threadsGet: 'threads.get',
  threadsSync: 'threads.sync',
  messagesGet: 'messages.get',
  draftsCreate: 'drafts.create',
  draftsSend: 'drafts.send',
  messagesMarkRead: 'messages.mark_read',
  labelsModify: 'labels.modify',
  attachmentsGet: 'attachments.get'
} as const;

export const MAIL_INTERACTIVE_SYNC_THREADS = 25;

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
