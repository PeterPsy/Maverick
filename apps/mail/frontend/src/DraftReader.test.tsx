// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DraftReader } from './DraftReader';
import type { MailDraft } from './api';

describe('Recorded draft delivery outcomes', () => {
  let container: HTMLDivElement;
  let root: Root;
  beforeEach(() => {
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
    container = document.createElement('div');
    document.body.append(container);
    root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  });
  async function render(status: string, result?: MailDraft['send_result']) {
    await act(async () => root.render(<DraftReader draft={{
      id: 'draft', connection_id: 'account', subject: 'Subject', body_text: 'Body',
      to: [{ email: 'accepted@example.com' }, { email: 'refused@example.com' }], status,
      send_result: result,
    }} onClose={() => undefined} />));
    return container.textContent || '';
  }

  it('shows accepted and refused recipients for partial submission', async () => {
    const text = await render('partially_sent', {
      status: 'partially_sent', accepted_recipients: ['accepted@example.com'],
      refused_recipients: { 'refused@example.com': { smtp_code: 550 } },
    });
    expect(text).toContain('Partially sent');
    expect(text).not.toContain('Draft · not sent');
    expect(container.querySelector('[aria-label="Accepted by provider"]')?.textContent).toContain('accepted@example.com');
    expect(container.querySelector('[aria-label="Refused by provider"]')?.textContent).toContain('refused@example.com');
    expect(text).toContain('SMTP 550');
  });
  it('explains that unknown delivery may already have happened', async () => {
    const text = await render('unknown');
    expect(text).toContain('Delivery not confirmed');
    expect(text).toContain('may have been accepted');
    expect(text).not.toContain('Draft · not sent');
  });
  it('shows an in-progress submission without claiming it is unsent', async () => {
    const text = await render('sending');
    expect(text).toContain('Sending · outcome pending');
    expect(text).not.toContain('Draft · not sent');
  });
  it.each([['draft', 'Draft · not sent'], ['failed', 'Send failed'], ['sent', 'Sent · accepted by provider']])('renders the %s state', async (state, label) => {
    expect(await render(state)).toContain(label);
  });
  it('does not infer recipient acceptance when partial details are unavailable', async () => {
    const text = await render('partially_sent');
    expect(text).toContain('Recipient outcomes are unavailable');
    expect(container.querySelector('[aria-label="Accepted by provider"]')).toBeNull();
  });
  it('treats an unrecognized persisted status conservatively', async () => {
    const text = await render('future-state');
    expect(text).toContain('Delivery not confirmed');
    expect(text).not.toContain('Draft · not sent');
  });
});
