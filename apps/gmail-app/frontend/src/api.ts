export type GmailMessage = {
  id: string;
  thread_id: string;
  from_email: string;
  to_emails: string[];
  subject: string;
  snippet: string;
  body_text: string;
  received_at: string;
  is_unread: boolean;
};

export type ThreadSummary = {
  id: string;
  subject: string;
  participants: string[];
  snippet: string;
  updated_at: string;
  is_unread: boolean;
  labels: string[];
  from_email?: string;
  to_emails?: string[];
  messages?: GmailMessage[];
};

export type Suggestion = {
  id: string;
  thread_id: string;
  kind: string;
  title: string;
  email: string;
  domain: string;
  note: string;
  status: string;
};

export type AuditEvent = {
  id: string;
  event_type: string;
  subject_id: string;
  created_at: string;
};

export type OAuthSession = {
  clientId: string;
  clientSecret: string;
  loginEmail: string;
  accessToken: string;
  email: string;
};

export async function callBackend<T>(body: Record<string, unknown>): Promise<T> {
  const response = await fetch('/api/apps/gmail-app/backend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const payload = await response.json();
  if (!response.ok || payload.error) {
    throw new Error(payload.detail || payload.error || `Request failed: ${response.status}`);
  }
  return payload as T;
}

export function loadOAuthSession(): OAuthSession {
  return {
    clientId: sessionStorage.getItem('gmail_app_client_id') || '',
    clientSecret: sessionStorage.getItem('gmail_app_client_secret') || '',
    loginEmail: sessionStorage.getItem('gmail_app_login_email') || '',
    accessToken: sessionStorage.getItem('gmail_app_access_token') || '',
    email: sessionStorage.getItem('gmail_app_email') || ''
  };
}

export function saveOAuthSession(update: Partial<OAuthSession>) {
  if (update.clientId !== undefined) sessionStorage.setItem('gmail_app_client_id', update.clientId);
  if (update.clientSecret !== undefined) sessionStorage.setItem('gmail_app_client_secret', update.clientSecret);
  if (update.loginEmail !== undefined) sessionStorage.setItem('gmail_app_login_email', update.loginEmail);
  if (update.accessToken !== undefined) sessionStorage.setItem('gmail_app_access_token', update.accessToken);
  if (update.email !== undefined) sessionStorage.setItem('gmail_app_email', update.email);
}

export function clearOAuthSession() {
  ['gmail_app_client_id', 'gmail_app_client_secret', 'gmail_app_login_email', 'gmail_app_access_token', 'gmail_app_email', 'gmail_app_code_verifier', 'gmail_app_oauth_state'].forEach((key) => sessionStorage.removeItem(key));
}
