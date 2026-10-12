import type { Inspection, Job, Plan, Verification } from './api';

export const escapeHtml = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
const e = escapeHtml;
const link = (url: string, label: string) => url.startsWith('https://') ? `<a href="${e(url)}" target="_blank" rel="noopener noreferrer">${e(label)} ↗</a>` : '';
const statusLabels: Record<string, string> = { queued: 'Queued', preparing: 'Preparing DNS & certificates', waiting_dns: 'Waiting for DNS', waiting_ca: 'Waiting for certificate authority', waiting_external_actions: 'Provider update needed', activating: 'Activating address', verifying: 'Checking the new connection', rolling_back: 'Restoring previous setup', rolled_back: 'Previous setup restored', ready: 'Ready', failed: 'Needs attention', rollback_requested: 'Restoration requested' };
export const statusLabel = (status: string) => statusLabels[status] || status;
const errorMessages: Record<string, string> = {
  dns_zone_not_authorized: 'This token cannot access the domain. Add Zone · DNS · Edit and Zone · Zone · Read for this domain.',
  dns_access_denied: 'Cloudflare rejected this connection. Check the token permissions in Vault.',
  dns_automation_connection_required: 'Connect Cloudflare to automate wildcard certificates and renewal. Other providers can delegate DNS to Cloudflare while keeping the domain at the same registrar.',
  invalid_hostname: 'Enter a public domain such as maverick.example.com, without a path or port.',
  invalid_server_ip: 'Enter the public IP address of this server.', public_server_ip_required: 'Use the public server IP.',
  stale_installation_plan: 'The setup changed. Review a fresh plan before applying.',
  installation_change_in_progress: 'An installation change is already running. Follow its progress below.',
  wrong_server_at_target_address: 'The address reaches another server. Check the public IP before retrying.',
  secure_connection_required: 'Open setup over HTTPS or a local connection before saving a credential.',
  admin_required: 'Sign in with a platform administrator account to configure this installation.',
  plan_integrity_failed: 'This plan changed after review. Create a fresh plan.',
  renewal_verification_failed: 'The automatic renewal test failed. Check DNS access before retrying.',
};
export const errorMessage = (code: string) => errorMessages[code] || 'The operation could not complete. Diagnostic: ' + code.replaceAll('_', ' ');

export function overviewHtml(data: Inspection): string {
  const config = data.configuration;
  const online = data.worker?.checked_at && Date.now() - Date.parse(data.worker.checked_at) < 20 * 60 * 1000;
  return `<section class="installation-card"><div class="installation-card-heading"><div><p class="installation-eyebrow">This installation</p><h2>${e(config.hostname || 'Choose your address')}</h2></div><span class="installation-badge">${config.managed ? 'Managed' : 'Setup available'}</span></div>
    <div class="installation-facts"><div><span>Public address</span><strong>${config.public_url ? link(config.public_url, config.public_url) : 'Not configured'}</strong></div><div><span>Automation</span><strong>${online ? 'Worker online' : 'Worker unavailable'}</strong></div><div><span>Certificate renewal</span><strong>${e(data.worker?.renewal_state || (config.managed ? 'Scheduled' : 'Complete setup to manage'))}</strong></div></div>
    ${!online ? '<p class="installation-muted">The server administrator can enable automation with <code>sudo /usr/bin/python3 scripts/deploy/install_installation_worker.py</code>.</p>' : ''}
    <div class="installation-actions"><button type="button" data-installation-action="verify">Check connection</button><a href="/setup" target="_blank" rel="noopener">Open recovery setup ↗</a></div></section>`;
}

export function planHtml(plan: Plan, busy: boolean): string {
  const blocked = plan.blocking_issues.some(item => item.code === 'dns_automation_connection_required');
  return `<section class="installation-card"><p class="installation-eyebrow">Review your setup</p><h2>${e(plan.hostname)}</h2><p class="installation-muted">Server ${e(plan.target_ip)} · DNS only · HTTPS with automatic renewal</p>
    <ul class="installation-records">${plan.dns_changes.map(item => `<li><code>${e(item.name)}</code><span>${item.action === 'keep' ? 'Already correct' : e(item.after?.type + ' → ' + item.after?.content)}</span></li>`).join('')}</ul>
    <p class="installation-muted">Certificates: ${plan.certificate_names.map(e).join(', ')}</p>
    ${plan.blocking_issues.map(item => `<div class="installation-notice">${item.code === 'dns_delegation_pending' ? `Set these nameservers at your registrar once, then Maverick will continue automatically: <ul>${(item.nameservers || []).map(name => `<li><code>${e(name)}</code></li>`).join('')}</ul>` : e(errorMessage(item.code))}</div>`).join('')}
    ${plan.external_actions.length ? '<p>Keep the current provider callback registered until the new connection is ready. Maverick will pause for your confirmation.</p>' : ''}
    <div class="installation-actions"><button class="installation-primary" type="button" data-installation-action="apply" ${blocked || busy ? 'disabled' : ''}>Apply setup</button>${plan.token_template_url ? link(plan.token_template_url, 'Scoped token template') : ''}</div></section>`;
}

export function jobHtml(job: Job, plan?: Plan): string {
  const active = !['ready', 'rolled_back', 'failed', 'rollback_requested'].includes(job.status);
  return `<section class="installation-card" aria-label="Installation progress"><div class="installation-card-heading"><h2>${e(statusLabel(job.status))}</h2><span class="installation-badge">${active ? 'In progress' : 'Completed check'}</span></div>
    <ol class="installation-steps"><li>DNS & delegation</li><li>Certificates & renewal test</li><li>Provider connections</li><li>Activate & verify</li></ol>
    <p class="installation-muted" role="status">${active ? 'This operation continues on the server if you close this page.' : ''}${job.retry_at ? ' Next check: ' + e(new Date(job.retry_at).toLocaleString()) : ''}</p>
    ${job.error_code ? `<p role="alert">${e(errorMessage(job.error_code))}</p>` : ''}
    ${job.status === 'waiting_external_actions' && plan ? `<form data-installation-confirm><p>Add each new address in its provider console, then confirm.</p>${plan.external_actions.map(item => `<label class="installation-confirm-row"><input type="checkbox" name="action_id" value="${e(item.id)}" ${job.confirmed_actions?.includes(item.id) ? 'checked' : ''}><span><strong>${e(item.label)}</strong><code>${e(item.url)}</code>${item.provider_url ? link(item.provider_url, 'Open provider') : ''}</span></label>`).join('')}<button class="installation-primary" type="submit">Confirm provider updates</button></form>` : ''}
    ${job.verification ? verificationHtml(job.verification) : ''}
    <div class="installation-actions">${job.status === 'failed' ? '<button type="button" data-installation-action="retry">Retry</button>' : ''}${job.status !== 'rolled_back' && job.status !== 'rollback_requested' ? '<button type="button" data-installation-action="rollback-review">Restore previous setup</button>' : ''}${job.status === 'ready' && plan ? link(plan.public_url, 'Open Maverick') : ''}</div>
    <div data-installation-rollback hidden><p>Restore the DNS and address settings saved before this change. Provider registrations remain under your control.</p><button type="button" data-installation-action="rollback">Confirm restoration</button></div></section>`;
}

export function verificationHtml(result: Verification): string {
  return `<div class="installation-verification" role="status"><strong>${result.healthy ? 'Connection verified' : 'Some connections need attention'}</strong><ul>${result.checks.map(item => `<li><code>${e(item.host)}</code><span>${item.healthy ? 'HTTPS ready' : e(item.error || 'Unavailable')}</span></li>`).join('')}</ul></div>`;
}
