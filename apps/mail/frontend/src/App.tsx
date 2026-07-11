import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { DragEvent } from 'react';
import {
  Archive,
  ChevronDown,
  KeyRound,
  Mail,
  MailOpen,
  RefreshCw,
  X
} from 'lucide-react';
import {
  callBackend,
  MAIL_BACKEND_ACTIONS,
  MAIL_INTERACTIVE_SYNC_THREADS,
  type MailAttachmentFetchResponse,
  type MailAddress,
  type MailConnection,
  type MailMessage,
  type MailThread
} from './api';
import SlidingPagination from './components/ui/sliding-pagination';
import { mailThreadDragPayloadFromThread, mountMailThreadDragPreview, writeMailThreadDragData } from './lib/mailThreadDragDrop';
import {
  DEFAULT_MAILBOX_SCOPE_IDS,
  isMailbox,
  mailboxScopeIdsFromParams,
  normalizeMailboxScopeIds,
  parseMailboxScopeId,
  primaryMailboxScope,
  serializeMailboxScopeIds
} from './mailboxScopes';

const MAIL_DATA_RESOURCES = new Set(['connections', 'drafts', 'threads', 'view-state']);
const GMAIL_OAUTH_SECRETS = ['gmail-oauth-client-id', 'gmail-oauth-client-secret'];
const GMAIL_REFRESH_SECRET = 'gmail-refresh-token';
const IMAP_SMTP_SECRET = 'mailbox-password';
const THREADS_PAGE_SIZE = 50;
const INLINE_IMAGE_MAX_BYTES = 2_000_000;
const READER_TEXT_BODY_CHARS = 12_000;
const READER_FULL_TEXT_BODY_CHARS = 50_000;
const READER_HTML_BODY_CHARS = 250_000;
const EMAIL_FRAME_MIN_HEIGHT = 180;
const EMAIL_FRAME_MAX_HEIGHT = 12_000;
const EMAIL_FRAME_MAX_WIDTH = 3_200;

type ConnectionPayload = {
  items: MailConnection[];
  required_secrets?: string[];
  callback_path?: string;
};

type MailNavigateParams = {
  add_account?: boolean;
  add_account_request_id?: string;
  mailbox?: string;
  mailbox_scopes?: string;
  connection_id?: string | null;
  query?: string;
  thread?: string;
};

type ThreadListPayload = {
  items: MailThread[];
  limit?: number;
  offset?: number;
  total_count?: number;
};

type SyncPayload = {
  sync?: {
    synced_messages?: number;
    synced_threads?: number;
    synced_at?: string;
  };
};

type InlineImageState = {
  status: 'loading' | 'ready' | 'error' | 'too_large';
  dataUrl?: string;
  detail?: string;
};

function StorageDeleteIcon({ className = '', size = 16 }: { className?: string; size?: number }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M4 7h16M10 11v6M14 11v6M6 7l1 14h10l1-14M9 7V4h6v3" />
    </svg>
  );
}

function noSecretRequest() {
  return { _app_secret_request: { logical_names: [], required: false } };
}

function gmailSecretRequest(connectionId?: string) {
  if (!connectionId) {
    return noSecretRequest();
  }
  return {
    _app_secret_request: {
      required: true,
      selectors: [
        { logical_names: GMAIL_OAUTH_SECRETS },
        {
          logical_names: [GMAIL_REFRESH_SECRET],
          resource_type: 'mail_connection',
          resource_id: connectionId
        }
      ]
    }
  };
}

function connectionSecretRequest(connection?: MailConnection | null) {
  if (!connection?.id) {
    return noSecretRequest();
  }
  if (connection.provider === 'imap_smtp') {
    return {
      _app_secret_request: {
        required: true,
        selectors: [
          {
            logical_names: [IMAP_SMTP_SECRET],
            resource_type: 'mail_connection',
            resource_id: connection.id
          }
        ]
      }
    };
  }
  return gmailSecretRequest(connection.id);
}

function mailboxScopeIdsForConnections(scopeIds: string[], connections: MailConnection[]) {
  const connectionIds = new Set(connections.map((connection) => connection.id));
  const filtered = normalizeMailboxScopeIds(scopeIds).filter((scopeId) => {
    const scope = parseMailboxScopeId(scopeId);
    return Boolean(scope && (!scope.connectionId || connectionIds.has(scope.connectionId)));
  });
  return filtered.length ? filtered : DEFAULT_MAILBOX_SCOPE_IDS;
}

function isUsableConnection(connection?: MailConnection | null) {
  return Boolean(connection && connection.status !== 'disconnected');
}

function openVaultIssues() {
  window.parent?.postMessage(
    {
      type: 'maverick.app.open-app',
      app_id: 'vault',
      params: { tab: 'issues', query: 'mail' }
    },
    window.location.origin
  );
}

function notifySelection(selection: Record<string, string | boolean | null | undefined>) {
  window.parent?.postMessage(
    {
      type: 'maverick.app.selection-changed',
      owner_app_id: 'mail',
      selection
    },
    window.location.origin
  );
}

function threadSender(thread: MailThread): MailAddress {
  return thread.participants[0] || { email: 'mail' };
}

function normalizeEmail(value?: string) {
  return String(value || '').trim().toLowerCase();
}

function addressLabel(address?: MailAddress | null) {
  const name = String(address?.name || '').trim();
  const email = String(address?.email || '').trim();
  return name || email || 'Mail';
}

function connectionLabel(connection?: MailConnection | null) {
  return String(connection?.display_name || connection?.email_address || '').trim() || 'Mail account';
}

function isConnectionParticipant(participant: MailAddress, connection?: MailConnection | null) {
  const participantEmail = normalizeEmail(participant.email);
  const connectionEmail = normalizeEmail(connection?.email_address);
  return Boolean(participantEmail && connectionEmail && participantEmail === connectionEmail);
}

function threadCounterparty(thread: MailThread, connection?: MailConnection | null): MailAddress {
  return thread.participants.find((participant) => !isConnectionParticipant(participant, connection))
    || thread.participants[0]
    || { email: 'mail' };
}

function threadRoute(thread: MailThread, connection?: MailConnection | null, mailbox?: string) {
  const account = connectionLabel(connection);
  const counterparty = addressLabel(threadCounterparty(thread, connection));
  const isSentOnlyThread = thread.labels.includes('sent') && !thread.labels.includes('inbox');
  if (mailbox === 'sent' || isSentOnlyThread) {
    return {
      fromLabel: account,
      toLabel: counterparty,
      title: `${account} to ${counterparty}`
    };
  }
  const sender = addressLabel(threadCounterparty(thread, connection));
  return {
    fromLabel: sender,
    toLabel: account,
    title: `${sender} to ${account}`
  };
}

function avatarInitials(thread: MailThread) {
  const sender = threadSender(thread);
  const source = sender.name || sender.email || 'Mail';
  const localPart = source.includes('@') ? source.split('@')[0] : source;
  const parts = localPart.split(/[\s._-]+/).filter(Boolean);
  const initials = parts.slice(0, 2).map((part) => part.slice(0, 1).toUpperCase()).join('');
  return initials || 'M';
}

function formatBytes(value?: number) {
  if (!value) {
    return '';
  }
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${Math.round(value / 1024)} KB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function formatAddress(address?: MailAddress) {
  if (!address) {
    return '';
  }
  return address.name ? `${address.name} <${address.email}>` : address.email;
}

function formatAddressList(addresses?: MailAddress[]) {
  return (addresses || []).map(formatAddress).filter(Boolean).join(', ');
}

function formatThreadDate(value?: string) {
  if (!value) {
    return '';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  const now = new Date();
  const options: Intl.DateTimeFormatOptions =
    date.getFullYear() === now.getFullYear()
      ? { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }
      : { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' };
  return date.toLocaleString(undefined, options);
}

function cidKey(value?: string) {
  const raw = String(value || '').trim();
  const withoutScheme = raw.toLowerCase().startsWith('cid:') ? raw.slice(4) : raw;
  try {
    return decodeURIComponent(withoutScheme).replace(/^<|>$/g, '').trim().toLowerCase();
  } catch {
    return withoutScheme.replace(/^<|>$/g, '').trim().toLowerCase();
  }
}

function safeImageContentType(value?: string) {
  const contentType = String(value || '').trim().toLowerCase();
  return /^image\/[a-z0-9.+-]+$/.test(contentType) ? contentType : 'image/png';
}

function base64UrlToBase64(value?: string) {
  const raw = String(value || '').trim();
  if (!/^[A-Za-z0-9_-]*={0,2}$/.test(raw)) {
    return null;
  }
  const unpadded = raw.replace(/=+$/g, '');
  if (unpadded.includes('=') || unpadded.length % 4 === 1) {
    return null;
  }
  return `${unpadded.replace(/-/g, '+').replace(/_/g, '/')}${'='.repeat((4 - (unpadded.length % 4)) % 4)}`;
}

function inlineImageDataUrl(dataBase64Url?: string, contentType?: string) {
  const dataBase64 = base64UrlToBase64(dataBase64Url);
  if (!dataBase64) {
    return null;
  }
  return `data:${safeImageContentType(contentType)};base64,${dataBase64}`;
}

function openBlankAuthorizationWindow() {
  const popup = window.open('about:blank', '_blank');
  if (!popup) {
    return null;
  }
  try {
    popup.document.title = 'Opening Gmail';
    popup.document.body.style.fontFamily = 'system-ui, sans-serif';
    popup.document.body.style.padding = '24px';
    popup.document.body.textContent = 'Opening Gmail...';
  } catch {
    return popup;
  }
  return popup;
}

function openAuthorizationUrl(authorizationUrl: string, popup: Window | null) {
  if (popup && !popup.closed) {
    popup.location.replace(authorizationUrl);
    try {
      popup.opener = null;
      popup.focus();
    } catch {
      return;
    }
    return;
  }
  if (window.top && window.top !== window) {
    window.parent.postMessage({ type: 'maverick.app.external-url', url: authorizationUrl }, window.location.origin);
    return;
  }
  window.location.assign(authorizationUrl);
}

function closeAuthorizationWindow(popup: Window | null) {
  if (popup && !popup.closed) {
    try {
      popup.close();
    } catch {
      return;
    }
  }
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function hasCidImagePlaceholder(htmlBody: string, contentId?: string) {
  const cid = String(contentId || '').trim();
  if (!cid) {
    return false;
  }
  const encodedCid = encodeURIComponent(cid);
  return [cid, encodedCid].some((candidate) => new RegExp(`data-mail-image=["']cid:${escapeRegExp(candidate)}`, 'i').test(htmlBody));
}

function applyImageMetadata(image: HTMLImageElement, placeholder: HTMLElement, fallbackAlt: string) {
  image.alt = placeholder.dataset.mailAlt || placeholder.textContent || fallbackAlt;
  image.decoding = 'async';
  if (placeholder.dataset.mailWidth) {
    image.setAttribute('width', placeholder.dataset.mailWidth);
  }
  if (placeholder.dataset.mailHeight) {
    image.setAttribute('height', placeholder.dataset.mailHeight);
  }
  const savedStyle = placeholder.dataset.mailStyle || '';
  if (savedStyle) {
    image.setAttribute('style', savedStyle);
  }
  image.style.border = '0';
}

function sizePlaceholder(element: HTMLElement) {
  const width = Number.parseInt(element.dataset.mailWidth || '', 10);
  const height = Number.parseInt(element.dataset.mailHeight || '', 10);
  if (Number.isFinite(width) && width > 0) {
    element.style.width = `${Math.min(width, 1200)}px`;
  }
  if (Number.isFinite(height) && height > 0) {
    element.style.height = `${Math.min(height, 1200)}px`;
  }
}

function annotateInlinePlaceholders(
  htmlBody: string,
  inlineAssets: MailMessage['inline_assets'],
  inlineImages: Record<string, InlineImageState>,
  showRemoteImages: boolean
) {
  if (!htmlBody || typeof DOMParser === 'undefined') {
    return htmlBody;
  }
  const doc = new DOMParser().parseFromString(`<div>${htmlBody}</div>`, 'text/html');
  const root = doc.body.firstElementChild;
  if (!root) {
    return htmlBody;
  }
  const assetsByCid = new Map((inlineAssets || []).filter((asset) => asset.content_id).map((asset) => [cidKey(asset.content_id), asset]));
  root.querySelectorAll<HTMLElement>('.mail-blocked-image[data-mail-image]').forEach((element) => {
    const imageSrc = element.dataset.mailImage || '';
    const asset = assetsByCid.get(cidKey(imageSrc));
    if (!asset) {
      sizePlaceholder(element);
      if (!showRemoteImages || !/^https?:\/\//i.test(imageSrc)) {
        return;
      }
      const image = doc.createElement('img');
      image.src = imageSrc;
      image.loading = 'lazy';
      image.referrerPolicy = 'no-referrer';
      applyImageMetadata(image, element, 'remote image');
      element.replaceWith(image);
      return;
    }
    element.dataset.mailAttachmentId = asset.attachment_id || '';
    sizePlaceholder(element);
    const loaded = asset.attachment_id ? inlineImages[asset.attachment_id] : undefined;
    if (loaded?.status === 'ready' && loaded.dataUrl) {
      const image = doc.createElement('img');
      image.src = loaded.dataUrl;
      applyImageMetadata(image, element, asset.filename || 'inline image');
      element.replaceWith(image);
      return;
    }
    if (loaded?.status === 'loading') {
      element.textContent = 'Loading inline image';
    } else if (loaded?.status === 'too_large') {
      element.textContent = 'Inline image too large';
    } else if (loaded?.status === 'error') {
      element.textContent = 'Inline image unavailable';
    }
    element.title = loaded?.detail || (asset.filename ? `Inline image: ${asset.filename}` : 'Inline image');
  });
  root.querySelectorAll<HTMLElement>('[data-mail-background-image]').forEach((element) => {
    const imageSrc = element.dataset.mailBackgroundImage || '';
    if (!showRemoteImages || !/^https?:\/\//i.test(imageSrc)) {
      return;
    }
    element.style.backgroundImage = `url("${imageSrc.replace(/"/g, '%22')}")`;
  });
  return root.innerHTML;
}

function foldQuotedHtml(htmlBody: string) {
  if (!htmlBody || typeof DOMParser === 'undefined') {
    return htmlBody;
  }
  const doc = new DOMParser().parseFromString(`<div>${htmlBody}</div>`, 'text/html');
  const root = doc.body.firstElementChild;
  if (!root) {
    return htmlBody;
  }
  root.querySelectorAll<HTMLElement>('blockquote.gmail_quote, div.gmail_quote, .gmail_quote').forEach((quote) => {
    if (quote.closest('.mail-quote-fold')) {
      return;
    }
    const details = doc.createElement('details');
    details.className = 'mail-quote-fold';
    details.dataset.mailReaderUi = 'quote-fold';
    const summary = doc.createElement('summary');
    summary.textContent = 'Show quoted text';
    quote.replaceWith(details);
    details.append(summary, quote);
  });
  return root.innerHTML;
}

function emailSrcDoc(htmlBody: string) {
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    html,
    body {
      margin: 0;
      padding: 0;
      background: #ffffff;
    }

    body {
      overflow-wrap: normal;
      word-break: normal;
    }

    img {
      border: 0;
    }

    .mail-blocked-image {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 2rem;
      min-height: 2rem;
      border: 1px dashed #cbd5e1;
      border-radius: 6px;
      background: #f8fafc;
      color: #64748b;
      padding: 0 10px;
      box-sizing: border-box;
      font: 12px Arial, Helvetica, sans-serif;
    }

    .mail-quote-fold {
      margin: 12px 0 0;
    }

    .mail-quote-fold > summary {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      border-radius: 999px;
      background: #f1f5f9;
      color: #475569;
      cursor: pointer;
      padding: 0 10px;
      font: 12px Arial, Helvetica, sans-serif;
    }

    .mail-quote-fold[open] > summary {
      margin-bottom: 8px;
    }
  </style>
</head>
<body>${htmlBody}</body>
</html>`;
}

function MailHtmlFrame({ htmlBody }: { htmlBody: string }) {
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const [height, setHeight] = useState(320);
  const [frameWidth, setFrameWidth] = useState<number | null>(null);
  const srcDoc = useMemo(() => emailSrcDoc(htmlBody), [htmlBody]);

  const resizeFrame = useCallback(() => {
    const frame = frameRef.current;
    const doc = frame?.contentDocument;
    if (!doc) {
      return;
    }
    const docElement = doc.documentElement;
    const body = doc.body;
    const contentHeight = Math.max(
      docElement.scrollHeight,
      docElement.offsetHeight,
      body?.scrollHeight || 0,
      body?.offsetHeight || 0
    );
    const contentWidth = Math.max(
      docElement.scrollWidth,
      docElement.offsetWidth,
      body?.scrollWidth || 0,
      body?.offsetWidth || 0
    );
    const parentWidth = frame.parentElement?.clientWidth || frame.clientWidth || 0;
    const nextHeight = Math.max(EMAIL_FRAME_MIN_HEIGHT, Math.min(EMAIL_FRAME_MAX_HEIGHT, Math.ceil(contentHeight)));
    const nextWidth = parentWidth && contentWidth > parentWidth + 1
      ? Math.min(EMAIL_FRAME_MAX_WIDTH, Math.ceil(contentWidth))
      : null;

    setHeight((current) => current === nextHeight ? current : nextHeight);
    setFrameWidth((current) => current === nextWidth ? current : nextWidth);
  }, []);

  useEffect(() => {
    setFrameWidth(null);
    const id = window.setTimeout(resizeFrame, 120);
    return () => window.clearTimeout(id);
  }, [srcDoc, resizeFrame]);

  useEffect(() => {
    if (!frameWidth) {
      return undefined;
    }
    const id = window.setTimeout(resizeFrame, 50);
    return () => window.clearTimeout(id);
  }, [frameWidth, resizeFrame]);

  useEffect(() => {
    const frame = frameRef.current;
    const doc = frame?.contentDocument;
    if (!doc) {
      return undefined;
    }
    let animationFrame = 0;
    const scheduleResize = () => {
      window.cancelAnimationFrame(animationFrame);
      animationFrame = window.requestAnimationFrame(resizeFrame);
    };
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(scheduleResize);
    if (observer) {
      observer.observe(doc.documentElement);
      if (doc.body) {
        observer.observe(doc.body);
      }
    }
    doc.querySelectorAll('img').forEach((image) => {
      image.addEventListener('load', scheduleResize);
      image.addEventListener('error', scheduleResize);
    });
    scheduleResize();
    return () => {
      window.cancelAnimationFrame(animationFrame);
      observer?.disconnect();
      doc.querySelectorAll('img').forEach((image) => {
        image.removeEventListener('load', scheduleResize);
        image.removeEventListener('error', scheduleResize);
      });
    };
  }, [srcDoc, resizeFrame]);

  return (
    <iframe
      ref={frameRef}
      title="Email HTML message"
      className="message-html-frame"
      sandbox="allow-popups allow-popups-to-escape-sandbox allow-same-origin"
      srcDoc={srcDoc}
      style={{ height, width: frameWidth ? `${frameWidth}px` : undefined }}
      onLoad={resizeFrame}
    />
  );
}

function MailMessageBody({
  message,
  connection,
  plain,
  showImages
}: {
  message: MailMessage;
  connection?: MailConnection;
  plain: boolean;
  showImages: boolean;
}) {
  const [inlineImages, setInlineImages] = useState<Record<string, InlineImageState>>({});
  const [expandedMessage, setExpandedMessage] = useState<MailMessage | null>(null);
  const [loadingExpandedBody, setLoadingExpandedBody] = useState(false);
  const [expandedBodyError, setExpandedBodyError] = useState('');
  const visibleMessage = expandedMessage || message;
  const htmlBody = visibleMessage.body_html_rendered || visibleMessage.body_html_sanitized || '';
  const renderedHtml = useMemo(
    () => foldQuotedHtml(annotateInlinePlaceholders(htmlBody, visibleMessage.inline_assets, inlineImages, showImages)),
    [htmlBody, inlineImages, visibleMessage.inline_assets, showImages]
  );
  const hasHtml = Boolean(htmlBody);
  const visibleBodyTruncated = Boolean(
    visibleMessage.body_source_truncated ||
    (plain
      ? (visibleMessage.body_text_truncated ?? visibleMessage.body_truncated)
      : (visibleMessage.body_html_truncated ?? visibleMessage.body_truncated))
  );
  const canLoadTrimmedContent = Boolean(
    !expandedMessage &&
    (message.body_text_truncated || message.body_html_truncated) &&
    !message.body_source_truncated
  );
  const inlineAssetsToFetch = useMemo(
    () => (visibleMessage.inline_assets || []).filter((asset) => {
      const contentId = asset.content_id || '';
      const attachmentId = asset.attachment_id || '';
      const contentType = asset.content_type || '';
      return contentId && attachmentId && contentType.toLowerCase().startsWith('image/') && hasCidImagePlaceholder(htmlBody, contentId);
    }),
    [htmlBody, visibleMessage.inline_assets]
  );
  const attachments = visibleMessage.attachments || [];

  useEffect(() => {
    setExpandedMessage(null);
    setLoadingExpandedBody(false);
    setExpandedBodyError('');
  }, [message.id]);

  const loadTrimmedContent = useCallback(async () => {
    setLoadingExpandedBody(true);
    setExpandedBodyError('');
    try {
      const payload = await callBackend<{ message: MailMessage }>({
        action: MAIL_BACKEND_ACTIONS.messagesGet,
        message_id: message.id,
        max_body_chars: READER_FULL_TEXT_BODY_CHARS,
        max_body_html_chars: READER_HTML_BODY_CHARS,
        ...noSecretRequest()
      });
      setExpandedMessage(payload.message);
    } catch (error) {
      setExpandedBodyError((error as Error).message);
    } finally {
      setLoadingExpandedBody(false);
    }
  }, [message.id]);

  useEffect(() => {
    let cancelled = false;
    setInlineImages((current) => {
      const next: Record<string, InlineImageState> = {};
      inlineAssetsToFetch.forEach((asset) => {
        if (asset.attachment_id && current[asset.attachment_id]) {
          next[asset.attachment_id] = current[asset.attachment_id];
        }
      });
      return next;
    });
    inlineAssetsToFetch.forEach((asset) => {
      const attachmentId = asset.attachment_id || '';
      if ((asset.size_bytes || 0) > INLINE_IMAGE_MAX_BYTES) {
        setInlineImages((current) => ({
          ...current,
          [attachmentId]: { status: 'too_large', detail: `Inline image exceeds ${formatBytes(INLINE_IMAGE_MAX_BYTES)}.` }
        }));
        return;
      }
      setInlineImages((current) => current[attachmentId] ? current : { ...current, [attachmentId]: { status: 'loading' } });
      callBackend<MailAttachmentFetchResponse>({
        action: MAIL_BACKEND_ACTIONS.attachmentsGet,
        attachment_id: attachmentId,
        metadata_only: false,
        max_bytes: INLINE_IMAGE_MAX_BYTES,
        ...connectionSecretRequest(connection)
      })
        .then((payload) => {
          if (cancelled) {
            return;
          }
          const dataUrl = inlineImageDataUrl(payload.fetch.data_base64url, payload.fetch.content_type || asset.content_type);
          const status = payload.fetch.status === 'too_large' ? 'too_large' : dataUrl ? 'ready' : 'error';
          setInlineImages((current) => ({
            ...current,
            [attachmentId]: {
              status,
              dataUrl: dataUrl || undefined,
              detail: payload.fetch.detail || (status === 'too_large' ? `Inline image exceeds ${formatBytes(payload.fetch.max_bytes || INLINE_IMAGE_MAX_BYTES)}.` : undefined)
            }
          }));
        })
        .catch((error: Error) => {
          if (!cancelled) {
            setInlineImages((current) => ({ ...current, [attachmentId]: { status: 'error', detail: error.message } }));
          }
        });
    });
    return () => {
      cancelled = true;
    };
  }, [connection, inlineAssetsToFetch]);

  return (
    <>
      {hasHtml && !plain ? (
        <div className="message-html">
          <MailHtmlFrame htmlBody={renderedHtml} />
        </div>
      ) : (
        <p className="message-plain">{visibleMessage.body_text}</p>
      )}
      {visibleBodyTruncated ? (
        <div className="message-trimmed">
          <span>{visibleMessage.body_source_truncated ? 'Original source clipped.' : 'Message content clipped.'}</span>
          {canLoadTrimmedContent ? (
            <button type="button" onClick={loadTrimmedContent} disabled={loadingExpandedBody}>
              {loadingExpandedBody ? 'Loading...' : 'Show trimmed content'}
            </button>
          ) : null}
        </div>
      ) : null}
      {expandedBodyError ? <small>{expandedBodyError}</small> : null}
      {attachments.length ? (
        <div className="attachment-list" aria-label="Attachments">
          {attachments.map((attachment) => (
            <span key={attachment.id} className="attachment-chip" title={attachment.content_type || attachment.filename}>
              <span className="attachment-icon" aria-hidden="true" />
              <span>{attachment.filename}</span>
              {formatBytes(attachment.size_bytes) ? <small>{formatBytes(attachment.size_bytes)}</small> : null}
            </span>
          ))}
        </div>
      ) : null}
    </>
  );
}

function MailThreadMessage({
  message,
  connection,
  plain,
  showImages
}: {
  message: MailMessage;
  connection?: MailConnection;
  plain: boolean;
  showImages: boolean;
}) {
  const sender = formatAddress(message.sender);
  const recipients = formatAddressList(message.recipients);
  const cc = formatAddressList(message.cc);

  return (
    <article className="message">
      <details className="message-head">
        <summary>
          <span className="message-head__sender">{sender}</span>
          <span className="message-head__date">{new Date(message.sent_at).toLocaleString()}</span>
          <ChevronDown size={15} strokeWidth={1.8} aria-hidden="true" />
        </summary>
        <dl className="message-meta">
          <div>
            <dt>From</dt>
            <dd>{sender}</dd>
          </div>
          {recipients ? (
            <div>
              <dt>To</dt>
              <dd>{recipients}</dd>
            </div>
          ) : null}
          {cc ? (
            <div>
              <dt>Cc</dt>
              <dd>{cc}</dd>
            </div>
          ) : null}
          <div>
            <dt>Date</dt>
            <dd>{new Date(message.sent_at).toLocaleString()}</dd>
          </div>
        </dl>
      </details>
      <MailMessageBody message={message} connection={connection} plain={plain} showImages={showImages} />
    </article>
  );
}

export function App() {
  const [connections, setConnections] = useState<MailConnection[]>([]);
  const [threads, setThreads] = useState<MailThread[]>([]);
  const [totalThreads, setTotalThreads] = useState(0);
  const [selectedThread, setSelectedThread] = useState<MailThread | null>(null);
  const [mailboxScopeIds, setMailboxScopeIds] = useState<string[]>(DEFAULT_MAILBOX_SCOPE_IDS);
  const [mailbox, setMailbox] = useState('inbox');
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [searchFocused, setSearchFocused] = useState(false);
  const [page, setPage] = useState(1);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [threadListLoading, setThreadListLoading] = useState(true);
  const [threadOpenLoading, setThreadOpenLoading] = useState(false);
  const [oauthCompleting, setOauthCompleting] = useState(false);
  const [accountModalOpen, setAccountModalOpen] = useState(false);
  const [readerPlain, setReaderPlain] = useState(false);
  const [readerShowImages, setReaderShowImages] = useState(false);
  const [draggingThreadId, setDraggingThreadId] = useState('');
  const threadListRequestRef = useRef(0);
  const threadOpenRequestRef = useRef(0);
  const selectedThreadRef = useRef<MailThread | null>(null);
  const dragPreviewRef = useRef<HTMLElement | null>(null);
  const serializedMailboxScopes = useMemo(() => serializeMailboxScopeIds(mailboxScopeIds), [mailboxScopeIds]);
  const primaryScope = useMemo(() => primaryMailboxScope(mailboxScopeIds), [mailboxScopeIds]);

  useEffect(() => () => cleanupThreadDragPreview(), []);

  useEffect(() => {
    selectedThreadRef.current = selectedThread;
  }, [selectedThread]);

  const secretRequestForConnectionId = useCallback((id?: string) => {
    if (!id) {
      return noSecretRequest();
    }
    return connectionSecretRequest(connections.find((item) => item.id === id));
  }, [connections]);

  const openThread = useCallback(async (threadId: string, connectionId?: string, refresh = false) => {
    const requestId = threadOpenRequestRef.current + 1;
    threadOpenRequestRef.current = requestId;
    setBusy(true);
    setThreadOpenLoading(true);
    if (!refresh) {
      setSelectedThread(null);
    }
    try {
      const payload = await callBackend<{ thread: MailThread }>({
        action: MAIL_BACKEND_ACTIONS.threadsGet,
        thread_id: threadId,
        max_body_chars: READER_TEXT_BODY_CHARS,
        max_body_html_chars: READER_HTML_BODY_CHARS,
        ...(refresh && connectionId ? secretRequestForConnectionId(connectionId) : noSecretRequest())
      });
      if (threadOpenRequestRef.current !== requestId) {
        return;
      }
      setSelectedThread(payload.thread);
      setConnectionId(payload.thread.connection_id);
      notifySelection({
        thread: payload.thread.id,
        mailbox,
        mailbox_scopes: serializedMailboxScopes,
        connection_id: payload.thread.connection_id
      });
    } catch (error) {
      if (threadOpenRequestRef.current === requestId) {
        setNotice(error instanceof Error ? error.message : 'Unable to open mail thread.');
      }
    } finally {
      if (threadOpenRequestRef.current === requestId) {
        setThreadOpenLoading(false);
        setBusy(false);
      }
    }
  }, [mailbox, secretRequestForConnectionId, serializedMailboxScopes]);

  const loadThreads = useCallback(async () => {
    const requestId = threadListRequestRef.current + 1;
    threadListRequestRef.current = requestId;
    setThreadListLoading(true);
    const offset = (page - 1) * THREADS_PAGE_SIZE;
    try {
      const connectionPayload = await callBackend<ConnectionPayload>({ action: MAIL_BACKEND_ACTIONS.connectionsList, ...noSecretRequest() });
      if (threadListRequestRef.current !== requestId) {
        return;
      }
      const nextConnections = connectionPayload.items;
      const nextMailboxScopeIds = mailboxScopeIdsForConnections(mailboxScopeIds, nextConnections);
      const nextSerializedMailboxScopes = serializeMailboxScopeIds(nextMailboxScopeIds);
      const nextPrimaryScope = primaryMailboxScope(nextMailboxScopeIds);
      const threadPayload = await callBackend<ThreadListPayload>({
        action: MAIL_BACKEND_ACTIONS.threadsList,
        mailbox: nextPrimaryScope.mailbox,
        mailbox_scopes: nextSerializedMailboxScopes,
        ...(nextPrimaryScope.connectionId ? { connection_id: nextPrimaryScope.connectionId } : {}),
        ...(query ? { query } : {}),
        max_threads: THREADS_PAGE_SIZE,
        offset,
        ...noSecretRequest()
      });
      if (threadListRequestRef.current !== requestId) {
        return;
      }
      setConnections(nextConnections);
      if (nextSerializedMailboxScopes !== serializedMailboxScopes) {
        setMailboxScopeIds(nextMailboxScopeIds);
        setMailbox(nextPrimaryScope.mailbox);
        setConnectionId(nextPrimaryScope.connectionId);
        notifySelection({
          mailbox: nextPrimaryScope.mailbox,
          mailbox_scopes: nextSerializedMailboxScopes,
          thread: null,
          connection_id: nextPrimaryScope.connectionId
        });
      }
      setThreads(threadPayload.items);
      setTotalThreads(threadPayload.total_count ?? threadPayload.items.length);
      const selected = selectedThreadRef.current;
      if (selected && !nextConnections.some((item) => item.id === selected.connection_id)) {
        setSelectedThread(null);
        notifySelection({
          mailbox: nextPrimaryScope.mailbox,
          mailbox_scopes: nextSerializedMailboxScopes,
          thread: null,
          connection_id: nextPrimaryScope.connectionId
        });
      }
    } catch (error) {
      if (threadListRequestRef.current !== requestId) {
        return;
      }
      throw error;
    } finally {
      if (threadListRequestRef.current === requestId) {
        setThreadListLoading(false);
      }
    }
  }, [connectionId, mailboxScopeIds, page, query, serializedMailboxScopes]);

  useEffect(() => {
    setPage(1);
  }, [query, serializedMailboxScopes]);

  useEffect(() => {
    if (!notice) {
      return undefined;
    }
    const timeout = window.setTimeout(() => setNotice(''), 5000);
    return () => window.clearTimeout(timeout);
  }, [notice]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const threadId = params.get('thread');
    const code = params.get('code');
    const state = params.get('state');
    if (code && state && !oauthCompleting) {
      setOauthCompleting(true);
      callBackend<{ status: string; detail?: string; connection_id?: string }>({
        action: MAIL_BACKEND_ACTIONS.connectionsCompleteOAuth,
        provider: 'gmail',
        code,
        state,
        _app_secret_request: {
          logical_names: ['gmail-oauth-client-id', 'gmail-oauth-client-secret'],
          required: true
        }
      })
        .then((payload) => {
          setNotice(payload.detail || `Gmail OAuth status: ${payload.status}`);
          window.history.replaceState({}, document.title, window.location.pathname);
          if (payload.connection_id) {
            return callBackend({
              action: MAIL_BACKEND_ACTIONS.threadsSync,
              connection_id: payload.connection_id,
              max_threads: MAIL_INTERACTIVE_SYNC_THREADS,
              ...gmailSecretRequest(payload.connection_id)
            }).then(() => loadThreads());
          }
          return loadThreads();
        })
        .catch((error: Error) => setNotice(error.message))
        .finally(() => setOauthCompleting(false));
      return;
    }
    if (threadId) {
      openThread(threadId).catch((error: Error) => setNotice(error.message));
    }
  }, [loadThreads, oauthCompleting, openThread]);

  useEffect(() => {
    loadThreads().catch((error: Error) => setNotice(error.message));
  }, [loadThreads]);

  useEffect(() => {
    const listener = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) {
        return;
      }
      const data = event.data as { type?: string; owner_app_id?: string; resource?: string; params?: MailNavigateParams };
      if (data?.type === 'maverick.app.navigate') {
        const params = data.params || {};
        if (data.params?.add_account) {
          setAccountModalOpen(true);
        }
        const nextMailbox = params.mailbox;
        const hasMailboxScopesParam = Object.prototype.hasOwnProperty.call(params, 'mailbox_scopes');
        const hasConnectionIdParam = Object.prototype.hasOwnProperty.call(params, 'connection_id');
        const nextConnectionId = typeof params.connection_id === 'string' && params.connection_id.trim()
          ? params.connection_id.trim()
          : null;
        const resolvedMailbox = isMailbox(nextMailbox) ? nextMailbox : mailbox;
        const shouldApplyMailboxScopes = hasMailboxScopesParam || isMailbox(nextMailbox) || hasConnectionIdParam;
        if (shouldApplyMailboxScopes) {
          const nextMailboxScopeIds = hasMailboxScopesParam
            ? mailboxScopeIdsFromParams(params as Record<string, unknown>, [])
            : mailboxScopeIdsFromParams(
              { mailbox: resolvedMailbox, connection_id: hasConnectionIdParam ? nextConnectionId : connectionId },
              mailboxScopeIds
            );
          const nextPrimaryScope = primaryMailboxScope(nextMailboxScopeIds);
          const nextSerializedScopes = serializeMailboxScopeIds(nextMailboxScopeIds);
          setPage(1);
          setMailboxScopeIds(nextMailboxScopeIds);
          setMailbox(nextPrimaryScope.mailbox);
          setConnectionId(nextPrimaryScope.connectionId);
          setSelectedThread(null);
          notifySelection({
            mailbox: nextPrimaryScope.mailbox,
            mailbox_scopes: nextSerializedScopes,
            thread: null,
            connection_id: nextPrimaryScope.connectionId
          });
        }
        if (typeof params.query === 'string') {
          setQuery(params.query);
        }
        if (params.thread) {
          openThread(params.thread).catch((error: Error) => setNotice(error.message));
        }
        return;
      }
      const mailDataChanged =
        (data?.type === 'maverick.app.data-changed' || data?.type === 'maverick.widget.data-changed') &&
        data.owner_app_id === 'mail' &&
        typeof data.resource === 'string' &&
        MAIL_DATA_RESOURCES.has(data.resource);
      if (mailDataChanged) {
        loadThreads().catch((error: Error) => setNotice(error.message));
      }
    };
    window.addEventListener('message', listener);
    return () => window.removeEventListener('message', listener);
  }, [connectionId, loadThreads, mailbox, mailboxScopeIds, openThread]);

  const connection = (connectionId ? connections.find((item) => item.id === connectionId) : null) || connections.find((item) => item.status !== 'disconnected') || connections[0];
  const connectionById = useMemo(() => new Map(connections.map((item) => [item.id, item])), [connections]);
  const canUseConnection = Boolean(connection && connection.status !== 'disconnected');
  const totalPages = Math.max(1, Math.ceil(totalThreads / THREADS_PAGE_SIZE));
  const visibleStart = totalThreads === 0 ? 0 : (page - 1) * THREADS_PAGE_SIZE + 1;
  const visibleEnd = totalThreads === 0 ? 0 : Math.min(page * THREADS_PAGE_SIZE, totalThreads);
  const selectedMessages = selectedThread?.messages || [];
  const readerHasHtml = selectedMessages.some((message) => Boolean(message.body_html_rendered || message.body_html_sanitized));
  const readerHasRemoteImages = selectedMessages.some((message) => {
    const htmlBody = message.body_html_rendered || message.body_html_sanitized || '';
    return /data-mail-(?:image|background-image)="https?:\/\//i.test(htmlBody);
  });

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  useEffect(() => {
    if (!accountModalOpen) {
      return undefined;
    }
    const listener = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setAccountModalOpen(false);
      }
    };
    window.addEventListener('keydown', listener);
    return () => window.removeEventListener('keydown', listener);
  }, [accountModalOpen]);

  useEffect(() => {
    setReaderPlain(false);
    setReaderShowImages(false);
  }, [selectedThread?.id]);

  function closeThread() {
    setSelectedThread(null);
    notifySelection({
      mailbox: primaryScope.mailbox,
      mailbox_scopes: serializedMailboxScopes,
      thread: null,
      connection_id: primaryScope.connectionId
    });
  }

  async function startGmailOAuth() {
    const authorizationWindow = openBlankAuthorizationWindow();
    setBusy(true);
    try {
      const payload = await callBackend<{ status: string; authorization_url?: string; detail?: string }>({
        action: MAIL_BACKEND_ACTIONS.connectionsStartOAuth,
        provider: 'gmail',
        redirect_uri: `${window.location.origin}/apps/mail/oauth/callback`,
        _app_secret_request: {
          logical_names: GMAIL_OAUTH_SECRETS,
          required: true
        }
      });
      if (payload.authorization_url) {
        setAccountModalOpen(false);
        openAuthorizationUrl(payload.authorization_url, authorizationWindow);
        return;
      }
      closeAuthorizationWindow(authorizationWindow);
      setNotice(payload.detail || `Gmail setup status: ${payload.status}`);
    } catch (error) {
      closeAuthorizationWindow(authorizationWindow);
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function preparePrivateEmail() {
    setBusy(true);
    try {
      const payload = await callBackend<{ connection_id: string; status: string }>({
        action: MAIL_BACKEND_ACTIONS.connectionsPrepareImapSmtp,
        ...noSecretRequest()
      });
      setConnectionId(payload.connection_id);
      setNotice(`Private Email ${payload.status}.`);
      await loadThreads();
      setAccountModalOpen(false);
      openVaultIssues();
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function refreshMailbox() {
    if (!canUseConnection || !connection) {
      setNotice('Connect a mail account before refreshing.');
      return;
    }
    setBusy(true);
    try {
      const payload = await callBackend<SyncPayload>({
        action: MAIL_BACKEND_ACTIONS.threadsSync,
        connection_id: connection.id,
        mailbox,
        mailbox_scopes: serializedMailboxScopes,
        ...(query ? { query } : {}),
        max_threads: MAIL_INTERACTIVE_SYNC_THREADS,
        ...connectionSecretRequest(connection)
      });
      const synced = payload.sync?.synced_messages ?? payload.sync?.synced_threads ?? 0;
      setNotice(synced > 0 ? `Synced ${synced} message${synced === 1 ? '' : 's'}.` : 'Sync completed. No new messages found.');
      await loadThreads();
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function markSelected(read: boolean) {
    if (!selectedThread) {
      return;
    }
    setBusy(true);
    try {
      const payload = await callBackend<{ thread: MailThread }>({
        action: MAIL_BACKEND_ACTIONS.messagesMarkRead,
        thread_id: selectedThread.id,
        read,
        ...connectionSecretRequest(connectionById.get(selectedThread.connection_id))
      });
      setSelectedThread(payload.thread);
      await loadThreads();
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function modifySelected(add: string[], remove: string[]) {
    if (!selectedThread) {
      return;
    }
    setBusy(true);
    try {
      const payload = await callBackend<{ thread: MailThread }>({
        action: MAIL_BACKEND_ACTIONS.labelsModify,
        thread_id: selectedThread.id,
        add,
        remove,
        ...connectionSecretRequest(connectionById.get(selectedThread.connection_id))
      });
      setSelectedThread(payload.thread);
      await loadThreads();
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function markThread(thread: MailThread, read: boolean) {
    setBusy(true);
    try {
      const payload = await callBackend<{ thread: MailThread }>({
        action: MAIL_BACKEND_ACTIONS.messagesMarkRead,
        thread_id: thread.id,
        read,
        ...connectionSecretRequest(connectionById.get(thread.connection_id))
      });
      setSelectedThread((current) => current?.id === payload.thread.id ? payload.thread : current);
      await loadThreads();
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function moveThreadToTrash(thread: MailThread) {
    setBusy(true);
    try {
      const payload = await callBackend<{ thread: MailThread }>({
        action: MAIL_BACKEND_ACTIONS.labelsModify,
        thread_id: thread.id,
        add: ['trash'],
        remove: ['inbox'],
        ...connectionSecretRequest(connectionById.get(thread.connection_id))
      });
      setSelectedThread((current) => current?.id === payload.thread.id ? payload.thread : current);
      setNotice('Moved to trash.');
      await loadThreads();
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function handleThreadDragStart(event: DragEvent<HTMLElement>, thread: MailThread) {
    cleanupThreadDragPreview();
    setDraggingThreadId(thread.id);
    writeMailThreadDragData(event.dataTransfer, mailThreadDragPayloadFromThread(thread));
    const dragPreview = mountMailThreadDragPreview(thread);
    if (dragPreview) {
      dragPreviewRef.current = dragPreview;
      event.dataTransfer.setDragImage(dragPreview, 22, 22);
    }
  }

  function handleThreadDragEnd() {
    setDraggingThreadId('');
    cleanupThreadDragPreview();
  }

  function cleanupThreadDragPreview() {
    dragPreviewRef.current?.remove();
    dragPreviewRef.current = null;
  }

  return (
    <main className={`mail-shell ${selectedThread || threadOpenLoading ? 'is-reading' : 'is-list-only'}`}>
      <div className={`toolbar ${searchFocused ? 'is-search-focused' : ''}`}>
        <label className="mail-search">
          <span className="mail-search__icon" aria-hidden="true" />
          <input
            aria-label="Search in Mail"
            value={query}
            onBlur={() => setSearchFocused(false)}
            onChange={(event) => setQuery(event.target.value)}
            onFocus={() => setSearchFocused(true)}
            placeholder="Search in Mail"
          />
        </label>
        <div className="mail-page-controls" aria-label="Mail pagination">
          <span className={`mail-page-range ${threadListLoading ? 'is-loading' : ''}`}>
            {threadListLoading ? <span aria-hidden="true" /> : `${visibleStart}-${visibleEnd}`}
          </span>
          <button
            type="button"
            className="mail-icon-button"
            onClick={refreshMailbox}
            disabled={busy || threadListLoading || !canUseConnection}
            aria-label="Refresh mailbox"
            title="Refresh mailbox"
          >
            <RefreshCw size={16} strokeWidth={1.8} aria-hidden="true" />
          </button>
          {totalPages > 1 ? (
            <SlidingPagination
              totalPages={totalPages}
              currentPage={page}
              onPageChange={setPage}
              maxVisiblePages={7}
            />
          ) : null}
        </div>
      </div>

      {accountModalOpen ? (
        <div className="mail-modal-backdrop" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) {
            setAccountModalOpen(false);
          }
        }}>
          <section className="mail-account-modal" role="dialog" aria-modal="true" aria-labelledby="mail-account-modal-title">
            <header className="mail-account-modal__header">
              <h2 id="mail-account-modal-title">Add account</h2>
              <button type="button" className="mail-icon-button" onClick={() => setAccountModalOpen(false)} aria-label="Close">
                <X size={16} strokeWidth={1.9} aria-hidden="true" />
              </button>
            </header>
            <div className="mail-account-modal__choices">
              <button type="button" className="mail-account-choice" onClick={startGmailOAuth} disabled={busy}>
                <span className="mail-account-choice__icon" aria-hidden="true">
                  <Mail size={18} strokeWidth={1.9} />
                </span>
                <span>
                  <strong>Gmail</strong>
                  <small>Open OAuth</small>
                </span>
              </button>
              <button type="button" className="mail-account-choice" onClick={preparePrivateEmail} disabled={busy}>
                <span className="mail-account-choice__icon" aria-hidden="true">
                  <KeyRound size={18} strokeWidth={1.9} />
                </span>
                <span>
                  <strong>Private Email</strong>
                  <small>Open Vault</small>
                </span>
              </button>
            </div>
            {connections.length ? (
              <div className="connection-status-row" aria-label="Connection status">
                {connections.map((item) => (
                  <span key={item.id} className={`connection-pill is-${item.status.replace(/[^a-z0-9_-]+/gi, '-')}`}>
                    {item.provider === 'imap_smtp' ? 'Private Email' : 'Gmail'}: {item.status}
                  </span>
                ))}
              </div>
            ) : null}
          </section>
        </div>
      ) : null}

      <div className="mail-workspace">
        <section className="thread-column">
          {notice ? <div className="mail-sidebar-notice" role="status" aria-live="polite">{notice}</div> : null}
          <div className="thread-list" aria-busy={threadListLoading}>
            {threadListLoading ? <MailThreadListSkeleton /> : null}
            {!threadListLoading && threads.length === 0 ? (
              <div className="thread-empty">
                {canUseConnection ? 'No threads match this view.' : 'Connect a mail account to load mail.'}
              </div>
            ) : null}
            {!threadListLoading ? threads.map((thread) => {
              const threadDate = formatThreadDate(thread.last_message_at);
              const canModifyThread = connectionById.get(thread.connection_id)?.status !== 'disconnected';
              const connection = connectionById.get(thread.connection_id);
              const route = threadRoute(thread, connection, primaryScope.mailbox);
              return (
                <article
                  key={thread.id}
                  className={`thread-row ${selectedThread?.id === thread.id ? 'selected' : ''} ${
                    draggingThreadId === thread.id ? 'is-dragging' : ''
                  }`}
                  draggable
                  onDragEnd={handleThreadDragEnd}
                  onDragStart={(event) => handleThreadDragStart(event, thread)}
                >
                  <button className="thread-row__body" type="button" onClick={() => openThread(thread.id, thread.connection_id)}>
                    <span className="thread-avatar" aria-hidden="true">{avatarInitials(thread)}</span>
                    <span className="thread-copy">
                      <span className="thread-title-line">
                        <span className="thread-title">{thread.subject}</span>
                        {threadDate ? <span className="thread-title-date">{threadDate}</span> : null}
                      </span>
                      <span className="thread-snippet">{thread.snippet}</span>
                    </span>
                  </button>
                  <span className="thread-side" aria-label={`Actions for ${thread.subject}`}>
                    <span className="thread-route" title={route.title}>
                      <span>{route.fromLabel}</span>
                      <span className="thread-route-arrow" aria-hidden="true" />
                      <span>{route.toLabel}</span>
                    </span>
                    <span className="thread-action-row">
                      <button
                        type="button"
                        className="thread-read-button"
                        onClick={() => markThread(thread, thread.unread)}
                        disabled={busy || !canModifyThread}
                        aria-label={thread.unread ? 'Mark read' : 'Mark unread'}
                        title={thread.unread ? 'Mark read' : 'Mark unread'}
                      >
                        {thread.unread ? (
                          <MailOpen size={15} strokeWidth={1.9} aria-hidden="true" />
                        ) : (
                          <Mail size={15} strokeWidth={1.9} aria-hidden="true" />
                        )}
                      </button>
                      <button
                        type="button"
                        className="thread-trash-button"
                        onClick={() => moveThreadToTrash(thread)}
                        disabled={busy || !canModifyThread || thread.labels.includes('trash')}
                        aria-label="Move to trash"
                        title="Move to trash"
                      >
                        <StorageDeleteIcon className="thread-trash-icon" size={16} />
                      </button>
                    </span>
                  </span>
                </article>
              );
            }) : null}
          </div>
        </section>

        {selectedThread ? (
          <section className="reader-column">
            <header className="reader-header">
              <div className="reader-actions">
                {readerHasHtml ? (
                  <div className="reader-view-actions">
                    <button type="button" onClick={() => setReaderPlain((value) => !value)}>
                      {readerPlain ? 'HTML' : 'Plain text'}
                    </button>
                    {!readerPlain && readerHasRemoteImages ? (
                      <button type="button" onClick={() => setReaderShowImages((value) => !value)}>
                        {readerShowImages ? 'Hide images' : 'Show images'}
                      </button>
                    ) : null}
                  </div>
                ) : null}
                <div className="reader-thread-actions">
                  <button
                    type="button"
                    onClick={() => markSelected(selectedThread.unread)}
                    disabled={busy}
                    aria-label={selectedThread.unread ? 'Mark read' : 'Mark unread'}
                    title={selectedThread.unread ? 'Mark read' : 'Mark unread'}
                  >
                    <MailOpen size={16} strokeWidth={1.8} aria-hidden="true" />
                  </button>
                  <button type="button" onClick={() => modifySelected([], ['inbox'])} disabled={busy} aria-label="Archive" title="Archive">
                    <Archive size={16} strokeWidth={1.8} aria-hidden="true" />
                  </button>
                  <button type="button" onClick={() => modifySelected(['trash'], ['inbox'])} disabled={busy} aria-label="Move to trash" title="Move to trash">
                    <StorageDeleteIcon size={16} />
                  </button>
                  <button
                    type="button"
                    onClick={() => openThread(selectedThread.id, selectedThread.connection_id, true)}
                    disabled={busy}
                    aria-label="Refresh"
                    title="Refresh"
                  >
                    <RefreshCw size={16} strokeWidth={1.8} aria-hidden="true" />
                  </button>
                  <button type="button" className="reader-close" onClick={closeThread} aria-label="Close mail">
                    <X size={16} strokeWidth={1.8} aria-hidden="true" />
                  </button>
                </div>
              </div>
              <div className="reader-title-block">
                <h1>{selectedThread.subject}</h1>
              </div>
            </header>
            <div className="message-stack">
              {(selectedThread.messages || []).map((message) => (
                <MailThreadMessage
                  key={message.id}
                  message={message}
                  connection={connectionById.get(selectedThread.connection_id)}
                  plain={readerPlain}
                  showImages={readerShowImages}
                />
              ))}
            </div>
          </section>
        ) : threadOpenLoading ? (
          <MailReaderSkeleton />
        ) : null}
      </div>
    </main>
  );
}

function MailThreadListSkeleton() {
  return (
    <div className="mail-thread-skeleton" role="status" aria-label="Mail threads are loading">
      {Array.from({ length: 8 }).map((_, index) => (
        <article className="mail-thread-skeleton__row" key={index} aria-hidden="true">
          <span className="mail-thread-skeleton__body">
            <span className="mail-app-skeleton__avatar" />
            <span className="mail-thread-skeleton__copy">
              <span className="mail-thread-skeleton__title-line">
                <span className="mail-app-skeleton__line mail-app-skeleton__line--title" />
                <span className="mail-app-skeleton__line mail-app-skeleton__line--date" />
              </span>
              <span className="mail-app-skeleton__line mail-app-skeleton__line--snippet" />
            </span>
          </span>
          <span className="mail-thread-skeleton__side">
            <span className="mail-app-skeleton__line mail-app-skeleton__line--route" />
            <span className="mail-thread-skeleton__actions">
              <span />
              <span />
            </span>
          </span>
        </article>
      ))}
    </div>
  );
}

function MailReaderSkeleton() {
  return (
    <section className="reader-column mail-reader-skeleton" role="status" aria-label="Mail message is loading" aria-busy="true">
      <header className="reader-header mail-reader-skeleton__header" aria-hidden="true">
        <span className="mail-reader-skeleton__actions">
          <span />
          <span />
          <span />
          <span />
        </span>
        <span className="mail-app-skeleton__line mail-app-skeleton__line--reader-title" />
      </header>
      <div className="message-stack mail-reader-skeleton__stack" aria-hidden="true">
        {Array.from({ length: 2 }).map((_, index) => (
          <article className="mail-reader-skeleton__message" key={index}>
            <span className="mail-app-skeleton__line mail-app-skeleton__line--message-meta" />
            <span className="mail-reader-skeleton__block">
              <span className="mail-app-skeleton__line mail-app-skeleton__line--body-wide" />
              <span className="mail-app-skeleton__line mail-app-skeleton__line--body" />
              <span className="mail-app-skeleton__line mail-app-skeleton__line--body-short" />
              <span className="mail-app-skeleton__line mail-app-skeleton__line--body" />
            </span>
          </article>
        ))}
      </div>
    </section>
  );
}
