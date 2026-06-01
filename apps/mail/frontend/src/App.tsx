import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Archive,
  ChevronDown,
  Forward,
  KeyRound,
  Mail,
  MailOpen,
  RefreshCw,
  Reply,
  X
} from 'lucide-react';
import {
  callBackend,
  MAIL_BACKEND_ACTIONS,
  MAIL_INTERACTIVE_SYNC_THREADS,
  type MailAttachmentFetchResponse,
  type MailAddress,
  type MailConnection,
  type MailDraft,
  type MailMessage,
  type MailThread
} from './api';
import SlidingPagination from './components/ui/sliding-pagination';

const MAILBOXES = ['inbox', 'sent', 'drafts', 'starred', 'trash'];
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

type SendResult = {
  dry_run?: boolean;
  requires_confirmation?: boolean;
  sent?: boolean;
  message_id?: string;
  provider_message_id?: string;
  thread_id?: string;
  draft?: MailDraft;
  thread?: MailThread;
};

type MailNavigateParams = {
  add_account?: boolean;
  add_account_request_id?: string;
  mailbox?: string;
  connection_id?: string;
  query?: string;
  thread?: string;
};

type ThreadListPayload = {
  items: MailThread[];
  limit?: number;
  offset?: number;
  total_count?: number;
};

type InlineImageState = {
  status: 'loading' | 'ready' | 'error' | 'too_large';
  dataUrl?: string;
  detail?: string;
};

type ComposerMode = 'reply' | 'forward' | 'compose';

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

function notifySelection(selection: Record<string, string | boolean | null>) {
  window.parent?.postMessage(
    {
      type: 'maverick.app.selection-changed',
      owner_app_id: 'mail',
      selection
    },
    window.location.origin
  );
}

function sendResultNotice(result: SendResult, confirm: boolean) {
  if (result.dry_run || !confirm) {
    return 'Dry-run ready. Confirm only when the user approves send.';
  }
  if (!result.sent) {
    return 'Send request completed.';
  }
  if (result.provider_message_id) {
    return `Sent with Gmail as provider message ${result.provider_message_id}.`;
  }
  if (result.message_id) {
    return `Sent with the local mail provider as message ${result.message_id}.`;
  }
  return 'Message sent.';
}

function threadSender(thread: MailThread): MailAddress {
  return thread.participants[0] || { email: 'mail' };
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

function replySubject(subject: string) {
  return /^re:/i.test(subject.trim()) ? subject : `Re: ${subject}`;
}

function forwardSubject(subject: string) {
  return /^fwd?:/i.test(subject.trim()) ? subject : `Fwd: ${subject}`;
}

function latestMessage(thread: MailThread | null) {
  const messages = thread?.messages || [];
  return messages.length ? messages[messages.length - 1] : null;
}

function forwardedBody(message: MailMessage | null, subject: string) {
  if (!message) {
    return '';
  }
  const lines = [
    '',
    '',
    '---------- Forwarded message ---------',
    `From: ${formatAddress(message.sender)}`,
    `Date: ${new Date(message.sent_at).toLocaleString()}`,
    `Subject: ${subject}`,
    `To: ${formatAddressList(message.recipients)}`,
    '',
    message.body_text || message.body_preview || ''
  ];
  return lines.join('\n');
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

function MailMessageBody({ message, connection }: { message: MailMessage; connection?: MailConnection }) {
  const [plain, setPlain] = useState(false);
  const [showImages, setShowImages] = useState(false);
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
  const hasRemoteImages = /data-mail-(?:image|background-image)="https?:\/\//i.test(htmlBody);
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
    setPlain(false);
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
      {hasHtml ? (
        <div className="message-body-actions">
          <button type="button" onClick={() => setPlain((value) => !value)}>
            {plain ? 'HTML' : 'Plain text'}
          </button>
        </div>
      ) : null}
      {hasHtml && !plain && hasRemoteImages ? (
        <div className={`message-image-control ${showImages ? 'is-enabled' : ''}`}>
          <span>{showImages ? 'Remote images visible' : 'Remote images blocked'}</span>
          <button type="button" onClick={() => setShowImages((value) => !value)}>
            {showImages ? 'Hide images' : 'Show images'}
          </button>
        </div>
      ) : null}
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

function MailThreadMessage({ message, connection }: { message: MailMessage; connection?: MailConnection }) {
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
      <MailMessageBody message={message} connection={connection} />
    </article>
  );
}

export function App() {
  const [connections, setConnections] = useState<MailConnection[]>([]);
  const [threads, setThreads] = useState<MailThread[]>([]);
  const [totalThreads, setTotalThreads] = useState(0);
  const [selectedThread, setSelectedThread] = useState<MailThread | null>(null);
  const [mailbox, setMailbox] = useState('inbox');
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [draft, setDraft] = useState({ to: '', subject: '', body_text: '' });
  const [composerMode, setComposerMode] = useState<ComposerMode>('compose');
  const [lastDraft, setLastDraft] = useState<MailDraft | null>(null);
  const [lastSendResult, setLastSendResult] = useState<SendResult | null>(null);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [oauthCompleting, setOauthCompleting] = useState(false);
  const [accountModalOpen, setAccountModalOpen] = useState(false);
  const composerBodyRef = useRef<HTMLTextAreaElement | null>(null);

  const secretRequestForConnectionId = useCallback((id?: string) => {
    if (!id) {
      return noSecretRequest();
    }
    return connectionSecretRequest(connections.find((item) => item.id === id));
  }, [connections]);

  const openThread = useCallback(async (threadId: string, connectionId?: string, refresh = false) => {
    setBusy(true);
    try {
      const payload = await callBackend<{ thread: MailThread }>({
        action: MAIL_BACKEND_ACTIONS.threadsGet,
        thread_id: threadId,
        max_body_chars: READER_TEXT_BODY_CHARS,
        max_body_html_chars: READER_HTML_BODY_CHARS,
        ...(refresh && connectionId ? secretRequestForConnectionId(connectionId) : noSecretRequest())
      });
      setSelectedThread(payload.thread);
      setConnectionId(payload.thread.connection_id);
      if (!refresh) {
        setComposerMode('reply');
        setDraft({ to: '', subject: replySubject(payload.thread.subject), body_text: '' });
        setLastDraft(null);
        setLastSendResult(null);
      }
      notifySelection({ thread: payload.thread.id, mailbox, connection_id: payload.thread.connection_id });
    } finally {
      setBusy(false);
    }
  }, [mailbox, secretRequestForConnectionId]);

  const loadThreads = useCallback(async () => {
    const offset = (page - 1) * THREADS_PAGE_SIZE;
    const [connectionPayload, threadPayload] = await Promise.all([
      callBackend<ConnectionPayload>({ action: MAIL_BACKEND_ACTIONS.connectionsList, ...noSecretRequest() }),
      callBackend<ThreadListPayload>({
        action: MAIL_BACKEND_ACTIONS.threadsList,
        mailbox,
        ...(connectionId ? { connection_id: connectionId } : {}),
        query,
        max_threads: THREADS_PAGE_SIZE,
        offset,
        ...noSecretRequest()
      })
    ]);
    setConnections(connectionPayload.items);
    setThreads(threadPayload.items);
    setTotalThreads(threadPayload.total_count ?? threadPayload.items.length);
  }, [connectionId, mailbox, page, query]);

  useEffect(() => {
    setPage(1);
  }, [mailbox, query]);

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
        if (data.params?.add_account) {
          setAccountModalOpen(true);
        }
        const nextMailbox = data.params?.mailbox;
        const nextConnectionIdParam = typeof data.params?.connection_id === 'string' && data.params.connection_id.trim()
          ? data.params.connection_id.trim()
          : null;
        const nextConnectionId = nextConnectionIdParam || connectionId;
        const resolvedMailbox = nextMailbox && MAILBOXES.includes(nextMailbox) ? nextMailbox : mailbox;
        if (nextMailbox && MAILBOXES.includes(nextMailbox)) {
          setPage(1);
          setMailbox(nextMailbox);
          setSelectedThread(null);
        }
        if (nextConnectionIdParam) {
          setPage(1);
          setConnectionId(nextConnectionIdParam);
          setSelectedThread(null);
        }
        if ((nextMailbox && MAILBOXES.includes(nextMailbox)) || nextConnectionId !== connectionId) {
          notifySelection({ mailbox: resolvedMailbox, thread: null, connection_id: nextConnectionId });
        }
        if (typeof data.params?.query === 'string') {
          setQuery(data.params.query);
        }
        if (data.params?.thread) {
          openThread(data.params.thread).catch((error: Error) => setNotice(error.message));
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
  }, [connectionId, loadThreads, mailbox, openThread]);

  const connection = (connectionId ? connections.find((item) => item.id === connectionId) : null) || connections.find((item) => item.status !== 'disconnected') || connections[0];
  const connectionById = useMemo(() => new Map(connections.map((item) => [item.id, item])), [connections]);
  const canUseConnection = Boolean(connection && connection.status !== 'disconnected');
  const totalPages = Math.max(1, Math.ceil(totalThreads / THREADS_PAGE_SIZE));
  const visibleStart = totalThreads === 0 ? 0 : (page - 1) * THREADS_PAGE_SIZE + 1;
  const visibleEnd = totalThreads === 0 ? 0 : Math.min(page * THREADS_PAGE_SIZE, totalThreads);
  const isContextualReply = Boolean(selectedThread && composerMode === 'reply');

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

  function focusComposer() {
    window.setTimeout(() => composerBodyRef.current?.focus(), 0);
  }

  function startReply() {
    if (!selectedThread) {
      return;
    }
    setComposerMode('reply');
    setDraft((current) => ({
      to: '',
      subject: composerMode === 'reply' && current.subject.trim() ? current.subject : replySubject(selectedThread.subject),
      body_text: composerMode === 'reply' ? current.body_text : ''
    }));
    focusComposer();
  }

  function startForward() {
    if (!selectedThread) {
      return;
    }
    const sourceMessage = latestMessage(selectedThread);
    setComposerMode('forward');
    setDraft({
      to: '',
      subject: forwardSubject(selectedThread.subject),
      body_text: forwardedBody(sourceMessage, selectedThread.subject)
    });
    focusComposer();
  }

  function closeThread() {
    setSelectedThread(null);
    setComposerMode('compose');
    notifySelection({ mailbox, thread: null });
  }

  async function startGmailOAuth() {
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
        window.location.assign(payload.authorization_url);
        return;
      }
      setNotice(payload.detail || `Gmail setup status: ${payload.status}`);
    } catch (error) {
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

  async function createDraft(event: FormEvent) {
    event.preventDefault();
    if (!canUseConnection || !connection) {
      setNotice('Connect a mail account before creating drafts.');
      return;
    }
    setBusy(true);
    try {
      const payload = await callBackend<{ draft: MailDraft }>({
        action: MAIL_BACKEND_ACTIONS.draftsCreate,
        connection_id: connection?.id,
        thread_id: isContextualReply ? selectedThread?.id : undefined,
        to: draft.to.trim() ? [{ email: draft.to.trim() }] : [],
        subject: draft.subject,
        body_text: draft.body_text
      });
      setLastDraft(payload.draft);
      setLastSendResult(null);
      setNotice('Draft saved. Preview before confirm.');
      setDraft({ to: '', subject: selectedThread ? replySubject(selectedThread.subject) : '', body_text: '' });
      setComposerMode(selectedThread ? 'reply' : 'compose');
      await loadThreads();
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function sendLastDraft(confirm: boolean) {
    if (!lastDraft) {
      return;
    }
    setBusy(true);
    try {
      const payload = await callBackend<{ result: SendResult }>({
        action: MAIL_BACKEND_ACTIONS.draftsSend,
        draft_id: lastDraft.id,
        confirm,
        ...(confirm ? secretRequestForConnectionId(lastDraft.connection_id) : noSecretRequest())
      });
      setLastSendResult(payload.result);
      setNotice(sendResultNotice(payload.result, confirm));
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

  return (
    <main className={`mail-shell ${selectedThread ? 'is-reading' : 'is-list-only'}`}>
      <div className="toolbar">
        <label className="mail-search">
          <span className="mail-search__icon" aria-hidden="true" />
          <input aria-label="Search in Mail" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search in Mail" />
        </label>
        <div className="mail-page-controls" aria-label="Mail pagination">
          <span className="mail-page-range">{visibleStart}-{visibleEnd}</span>
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
          <div className="thread-list">
            {threads.length === 0 ? (
              <div className="thread-empty">
                {canUseConnection ? 'No threads match this view.' : 'Connect a mail account to load mail.'}
              </div>
            ) : null}
            {threads.map((thread) => {
              const sender = threadSender(thread);
              const canModifyThread = connectionById.get(thread.connection_id)?.status !== 'disconnected';
              const recipient = connectionById.get(thread.connection_id);
              const recipientLabel = recipient?.display_name || recipient?.email_address || 'Mail account';
              return (
                <article key={thread.id} className={`thread-row ${selectedThread?.id === thread.id ? 'selected' : ''}`}>
                  <button className="thread-row__body" type="button" onClick={() => openThread(thread.id, thread.connection_id)}>
                    <span className="thread-avatar" aria-hidden="true">{avatarInitials(thread)}</span>
                    <span className="thread-copy">
                      <span className="thread-title">{thread.subject}</span>
                      <span className="thread-snippet">{thread.snippet}</span>
                    </span>
                  </button>
                  <span className="thread-side" aria-label={`Actions for ${thread.subject}`}>
                    <span className="thread-route" title={`${sender.name || sender.email} to ${recipientLabel}`}>
                      <span>{sender.name || sender.email}</span>
                      <span className="thread-route-arrow" aria-hidden="true" />
                      <span>{recipientLabel}</span>
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
            })}
          </div>
          {!selectedThread && notice ? <div className="notice">{notice}</div> : null}
        </section>

        {selectedThread ? (
          <section className="reader-column">
          <header className="reader-header">
            <div>
              <h1>{selectedThread.subject}</h1>
              <p>{selectedThread.participants.map((person) => person.name || person.email).join(', ')}</p>
            </div>
            <div className="reader-actions">
              <button type="button" onClick={startReply} disabled={busy}>
                <Reply size={16} strokeWidth={1.8} aria-hidden="true" />
                Reply
              </button>
              <button type="button" onClick={startForward} disabled={busy}>
                <Forward size={16} strokeWidth={1.8} aria-hidden="true" />
                Forward
              </button>
              <button type="button" onClick={() => markSelected(selectedThread.unread)} disabled={busy}>
                <MailOpen size={16} strokeWidth={1.8} aria-hidden="true" />
                {selectedThread.unread ? 'Mark read' : 'Mark unread'}
              </button>
              <button type="button" onClick={() => modifySelected([], ['inbox'])} disabled={busy}>
                <Archive size={16} strokeWidth={1.8} aria-hidden="true" />
                Archive
              </button>
              <button type="button" onClick={() => modifySelected(['trash'], ['inbox'])} disabled={busy}>
                <StorageDeleteIcon size={16} />
                Trash
              </button>
              <button type="button" onClick={() => openThread(selectedThread.id, selectedThread.connection_id, true)} disabled={busy}>
                <RefreshCw size={16} strokeWidth={1.8} aria-hidden="true" />
                Refresh
              </button>
              <button type="button" className="reader-close" onClick={closeThread} aria-label="Close mail">
                <X size={16} strokeWidth={1.8} aria-hidden="true" />
              </button>
            </div>
          </header>
          <div className="message-stack">
            {(selectedThread.messages || []).map((message) => (
              <MailThreadMessage key={message.id} message={message} connection={connectionById.get(selectedThread.connection_id)} />
            ))}
          </div>
          {canUseConnection && connection ? (
            <form className="composer" onSubmit={createDraft}>
              {selectedThread ? (
                <div className="composer-mode" aria-label="Draft mode">
                  <button type="button" className={composerMode === 'reply' ? 'is-active' : ''} onClick={startReply}>
                    <Reply size={15} strokeWidth={1.8} aria-hidden="true" />
                    Reply
                  </button>
                  <button type="button" className={composerMode === 'forward' ? 'is-active' : ''} onClick={startForward}>
                    <Forward size={15} strokeWidth={1.8} aria-hidden="true" />
                    Forward
                  </button>
                </div>
              ) : null}
              <input
                value={draft.to}
                onChange={(event) => setDraft({ ...draft, to: event.target.value })}
                aria-label={isContextualReply ? 'Reply recipients' : composerMode === 'forward' ? 'Forward recipient email' : 'Recipient email'}
                placeholder={isContextualReply ? 'Reply recipients (optional)' : composerMode === 'forward' ? 'Forward to' : 'Recipient email'}
                required={!isContextualReply}
              />
              <input value={draft.subject} onChange={(event) => setDraft({ ...draft, subject: event.target.value })} placeholder="Subject" required />
              <textarea ref={composerBodyRef} value={draft.body_text} onChange={(event) => setDraft({ ...draft, body_text: event.target.value })} placeholder={composerMode === 'forward' ? 'Add a note' : 'Write a draft'} required />
              <div className="composer-actions">
                <button type="submit" disabled={busy}>Save draft</button>
                <button type="button" onClick={() => sendLastDraft(false)} disabled={busy || !lastDraft}>Preview send</button>
                <button type="button" onClick={() => sendLastDraft(true)} disabled={busy || !lastDraft}>Confirm send</button>
              </div>
            </form>
          ) : null}
          {lastDraft ? <p className="draft-note">Last draft: {lastDraft.subject}</p> : null}
          {lastSendResult?.dry_run ? <p className="draft-note">Dry-run prepared for draft {lastSendResult.draft?.id}.</p> : null}
          {lastSendResult?.sent ? <p className="draft-note">{sendResultNotice(lastSendResult, true)}</p> : null}
          {notice ? <div className="notice">{notice}</div> : null}
          </section>
        ) : null}
      </div>
    </main>
  );
}
