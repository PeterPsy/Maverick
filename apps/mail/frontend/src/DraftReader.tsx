import { X } from 'lucide-react';
import type { MailAddress, MailConnection, MailDraft } from './api';

function formatAddress(address: MailAddress) {
  return address.name ? `${address.name} <${address.email}>` : address.email;
}

function formatAddresses(addresses?: MailAddress[]) {
  return (addresses || []).map(formatAddress).join(', ');
}

export function DraftReader({
  connection,
  draft,
  onClose,
}: {
  connection?: MailConnection;
  draft: MailDraft;
  onClose: () => void;
}) {
  const sender = connection?.display_name || connection?.email_address || 'Mail account';
  const updatedAt = draft.updated_at ? new Date(draft.updated_at).toLocaleString() : '';
  return (
    <section className="reader-column draft-reader">
      <header className="reader-header">
        <div className="reader-actions">
          <span className="draft-reader__status">Draft · not sent</span>
          <div className="reader-thread-actions">
            <button type="button" className="reader-close" onClick={onClose} aria-label="Close draft">
              <X size={16} strokeWidth={1.8} aria-hidden="true" />
            </button>
          </div>
        </div>
        <div className="reader-title-block">
          <h1>{draft.subject}</h1>
        </div>
      </header>
      <div className="message-stack">
        <article className="message">
          <dl className="message-meta">
            <div><dt>From</dt><dd>{sender}</dd></div>
            <div><dt>To</dt><dd>{formatAddresses(draft.to)}</dd></div>
            {draft.cc?.length ? <div><dt>Cc</dt><dd>{formatAddresses(draft.cc)}</dd></div> : null}
            {draft.bcc?.length ? <div><dt>Bcc</dt><dd>{formatAddresses(draft.bcc)}</dd></div> : null}
            {updatedAt ? <div><dt>Updated</dt><dd>{updatedAt}</dd></div> : null}
          </dl>
          <p className="message-plain">{draft.body_text}</p>
        </article>
      </div>
    </section>
  );
}
