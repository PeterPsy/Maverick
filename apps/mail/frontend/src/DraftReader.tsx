import { X } from 'lucide-react';
import type { MailAddress, MailConnection, MailDraft } from './api';
import { accountLabel } from './accountLabels';

function formatAddress(address: MailAddress) {
  return address.name ? `${address.name} <${address.email}>` : address.email;
}

function formatAddresses(addresses?: MailAddress[]) {
  return (addresses || []).map(formatAddress).join(', ');
}

const deliveryCopy: Record<string, { label: string; detail: string }> = {
  draft: { label: 'Draft · not sent', detail: '' },
  sending: { label: 'Sending · outcome pending', detail: 'Submission is in progress or its result has not been recorded. Check the outcome before sending another copy.' },
  partially_sent: { label: 'Partially sent', detail: 'Some recipients were accepted by the provider and others were refused. Sending another copy to everyone may duplicate delivery.' },
  unknown: { label: 'Delivery not confirmed', detail: 'The message may have been accepted by the provider. Check the provider and Sent folder before sending another copy.' },
  failed: { label: 'Send failed', detail: 'The submission failed before provider acceptance or was explicitly rejected.' },
  sent: { label: 'Sent · accepted by provider', detail: 'The provider accepted the message. This does not confirm delivery to each inbox.' },
};

export function DraftReader({
  connection,
  draft,
  onClose,
}: {
  connection?: MailConnection;
  draft: MailDraft;
  onClose: () => void;
}) {
  const sender = accountLabel(connection);
  const updatedAt = draft.updated_at ? new Date(draft.updated_at).toLocaleString() : '';
  const delivery = deliveryCopy[draft.status] || deliveryCopy.unknown;
  const accepted = draft.send_result?.accepted_recipients || [];
  const refused = Object.entries(draft.send_result?.refused_recipients || {});
  return (
    <section className="reader-column draft-reader">
      <header className="reader-header">
        <div className="reader-actions">
          <span className="draft-reader__status" data-state={draft.status}>{delivery.label}</span>
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
          {draft.status !== 'draft' ? (
            <section className="draft-delivery" aria-label="Delivery outcome">
              <p>{delivery.detail}</p>
              {accepted.length ? (
                <div aria-label="Accepted by provider"><h2>Accepted by provider</h2><ul>{accepted.map((email) => <li key={email}>{email}</li>)}</ul></div>
              ) : null}
              {refused.length ? (
                <div aria-label="Refused by provider"><h2>Refused by provider</h2><ul>{refused.map(([email, outcome]) => <li key={email}>{email} <span>(SMTP {outcome.smtp_code})</span></li>)}</ul></div>
              ) : null}
              {draft.status === 'partially_sent' && !accepted.length && !refused.length ? <p>Recipient outcomes are unavailable. Check the provider before sending another copy.</p> : null}
            </section>
          ) : null}
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
