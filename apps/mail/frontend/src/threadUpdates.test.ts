import { describe, expect, it } from 'vitest';
import type { MailThread } from './api';
import { mergeThreadState } from './threadUpdates';

describe('Mail reader metadata updates', () => {
  it('retains full bodies and attachment metadata when a short mutation response changes message labels', () => {
    const current = {
      id: 'thread', subject: 'Subject', unread: true, labels: ['inbox', 'unread'],
      messages: [{ id: 'message', body_text: 'Full body retained', body_html_rendered: '<p>Full HTML</p>',
        labels: ['inbox', 'unread'], attachments: [{ id: 'attachment', file_name: 'fixture.txt' }] }],
    } as unknown as MailThread;
    const next = { ...current, unread: false, labels: ['inbox'],
      messages: [{ id: 'message', body_text: 'Short', labels: ['inbox'], attachments: [] }],
    } as unknown as MailThread;
    const result = mergeThreadState(current, next);
    expect(result.unread).toBe(false);
    expect(result.messages?.[0]).toMatchObject({ body_text: 'Full body retained', body_html_rendered: '<p>Full HTML</p>',
      labels: ['inbox'], attachments: [{ id: 'attachment', file_name: 'fixture.txt' }] });
    expect(current.messages?.[0].labels).toEqual(['inbox', 'unread']);
  });
});
