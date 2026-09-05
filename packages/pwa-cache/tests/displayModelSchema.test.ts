import { describe, expect, it } from 'vitest';
import { projectDisplayModel } from '../src/displayModelSchema';
import crmSchemas from '../../../apps/crm/pwa_read_models.v1.json';
import mailSchemas from '../../../apps/mail/pwa_read_models.v1.json';

describe('approved customer read-model schemas', () => {
  it('removes CRM workflow authority, secret custom fields and nested provider payloads', () => {
    const result = projectDisplayModel({ record: { id: 'c', display_name: 'Customer', custom_fields: { secret_token: 'secret', region: 'EU' }, authority: 'secret', provider_state: { key: 'secret' } }, admission: 'secret' }, crmSchemas.get);
    expect(result).toEqual({ record: { id: 'c', display_name: 'Customer', custom_fields: { region: 'EU' } } });
  });
  it('keeps consulted Mail body text but never active HTML, signed URLs or attachment bytes', () => {
    const result = projectDisplayModel({ message: { id: 'm', thread_id: 't', body_text: 'Full message', body_html_sanitized: '<script>secret</script>', attachments: [{ id: 'a', filename: 'File', data_base64url: 'secret', signed_url: 'secret' }] } }, mailSchemas.message);
    expect(result).toEqual({ message: { id: 'm', thread_id: 't', body_text: 'Full message', attachments: [{ id: 'a', filename: 'File' }] } });
  });
  it('projects connection display without its status, settings or OAuth material', () => {
    expect(projectDisplayModel({ items: [{ id: 'c', display_name: 'Mail', status: 'connected', settings: { password: 'secret' }, scopes: ['send'] }], folders: [] }, mailSchemas.mailboxes))
      .toEqual({ items: [{ id: 'c', display_name: 'Mail' }], folders: [] });
  });
  it('does not silently truncate legitimate large text and rejects malformed fields', () => {
    const body = 'x'.repeat(1048577);
    expect(projectDisplayModel({ message: { id: 'm', thread_id: 't', body_text: body } }, mailSchemas.message)?.message).toMatchObject({ body_text: body });
    expect(projectDisplayModel({ message: { id: 'm', thread_id: 't', body_text: {} } }, mailSchemas.message)).toBeNull();
    expect(projectDisplayModel({ items: [null] }, mailSchemas.threads)).toBeNull();
  });
});
