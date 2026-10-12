import { installationRequest, InstallationApiError, saveDnsCredential, terminalJob, type Inspection, type Job, type Plan, type Verification } from './api';
import { errorMessage, escapeHtml as e, jobHtml, overviewHtml, planHtml, verificationHtml } from './content';

export function mountInstallation(root: HTMLElement) {
  let data: Inspection | undefined;
  let plan: Plan | undefined;
  let jobPlan: Plan | undefined;
  let job: Job | undefined;
  let busy = false;
  let revision = 0;
  const actionDrafts = new Map<string, string[]>();
  let disposed = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const requests = new Set<AbortController>();
  root.classList.add('installation-view');
  root.innerHTML = `<div data-installation-overview><p role="status">Loading installation…</p></div><div data-installation-message role="status" aria-live="polite"></div>
    <form class="installation-card" data-installation-form><p class="installation-eyebrow">Address & connection</p><h2>Give Maverick a home</h2><p class="installation-muted">Use a domain you own. Maverick connects DNS, secures the address and checks its apps.</p>
    <label class="installation-field">Public address<input data-settings-controlled name="address" placeholder="maverick.example.com" required autocomplete="url" spellcheck="false"></label>
    <div class="installation-columns"><label class="installation-field">DNS provider<select data-settings-controlled name="dns_provider"><option value="cloudflare">Cloudflare · automatic</option><option value="manual">Another provider · guided</option></select></label>
    <label class="installation-field">Vault connection<select data-settings-controlled name="dns_secret_ref" aria-label="Vault connection"><option value="">Choose a connection</option></select></label></div>
    <details data-installation-credential><summary>Add a Cloudflare connection</summary><p class="installation-muted">Create a token with Zone · DNS · Edit and Zone · Zone · Read, restricted to your domain. The token is saved in Vault.</p><a href="https://dash.cloudflare.com/profile/api-tokens" target="_blank" rel="noopener noreferrer">Create a token ↗</a>
    <label class="installation-field">API token<input data-settings-controlled data-installation-token type="password" autocomplete="new-password" spellcheck="false"></label><button type="button" data-installation-action="save-token">Save in Vault</button></details>
    <details><summary>Server settings</summary><label class="installation-field">Public server IP<input data-settings-controlled name="target_ip" placeholder="Detected automatically" required spellcheck="false"></label><p class="installation-muted">Check this value if the server uses NAT or a separate public IP.</p></details>
    <div class="installation-actions"><button class="installation-primary" type="submit">Review setup</button></div></form><div data-installation-plan></div><div data-installation-job></div><div data-installation-verification></div>`;
  const query = <T extends Element = HTMLElement>(selector: string) => root.querySelector<T>(selector)!;
  const form = query<HTMLFormElement>('[data-installation-form]');
  const token = query<HTMLInputElement>('[data-installation-token]');
  const message = (text: string, error = false) => {
    if (disposed) return;
    const element = query('[data-installation-message]');
    element.textContent = text; element.setAttribute('role', error ? 'alert' : 'status');
  };
  function redraw() {
    if (disposed) return;
    const confirmation = root.querySelector<HTMLFormElement>('[data-installation-confirm]');
    if (confirmation) actionDrafts.set(confirmation.dataset.installationConfirm!, new FormData(confirmation).getAll('action_id').map(String));
    query('[data-installation-plan]').innerHTML = plan ? planHtml(plan, busy) : '';
    query('[data-installation-job]').innerHTML = job ? jobHtml(job, jobPlan) : '';
    if (job && actionDrafts.has(job.job_id)) root.querySelectorAll<HTMLInputElement>('[data-installation-confirm] input').forEach(input => { input.checked = actionDrafts.get(job!.job_id)!.includes(input.value); });
    root.querySelectorAll<HTMLButtonElement>('[data-installation-job] button').forEach(button => { button.disabled = busy; });
    form.querySelectorAll<HTMLButtonElement>('button').forEach(button => { button.disabled = busy; });
  }
  async function run<T>(operation: (signal: AbortSignal) => Promise<T>, action = true): Promise<T | undefined> {
    const controller = new AbortController(); requests.add(controller);
    if (action) { revision += 1; busy = true; redraw(); message('Working…'); }
    try {
      const result = await operation(controller.signal);
      if (disposed) return undefined;
      if (action) message('');
      return result;
    } catch (error) {
      if (!disposed && !controller.signal.aborted) message(error instanceof InstallationApiError ? errorMessage(error.code) : 'Reconnecting to the server. Progress will resume automatically.', true);
      return undefined;
    } finally { requests.delete(controller); if (action) { busy = false; redraw(); } }
  }
  async function refresh(initial = false) {
    const requestedRevision = revision;
    const inspected = await run(signal => installationRequest<Inspection>('inspect', undefined, signal), false);
    if (disposed) return;
    if (inspected && requestedRevision === revision) {
      data = inspected;
      query('[data-installation-overview]').innerHTML = overviewHtml(data);
      const refs = query<HTMLSelectElement>('[name=dns_secret_ref]');
      const selected = refs.value;
      refs.innerHTML = '<option value="">Choose a connection</option>' + data.dns_credentials.map(item => `<option value="${e(item.ref)}">${e(item.label)}</option>`).join('');
      refs.value = data.dns_credentials.some(item => item.ref === selected) ? selected : data.dns_credentials[0]?.ref || '';
      if (initial) {
        query<HTMLInputElement>('[name=address]').value = data.configuration.hostname;
        query<HTMLInputElement>('[name=target_ip]').value = data.configuration.target_ip || data.worker?.public_ip || '';
      }
      job = data.latest_job || job;
      if (job) {
        const result = await run(signal => installationRequest<{ job: Job; plan: Plan }>('status', { job_id: job!.job_id }, signal), false);
        if (result && requestedRevision === revision) { job = result.job; jobPlan = result.plan; }
      }
      redraw();
    }
    if (!disposed) timer = setTimeout(() => { void refresh(); }, job && !terminalJob(job) ? 5000 : 30000);
  }
  const onSubmit = async (event: Event) => {
    const target = event.target as HTMLFormElement;
    if (target === form) {
      event.preventDefault(); if (busy) return;
      const values = new FormData(form);
      const result = await run(signal => installationRequest<Plan>('plan', Object.fromEntries(values.entries()), signal));
      if (result) { plan = result; redraw(); query('[data-installation-plan]').scrollIntoView?.({ block: 'nearest', behavior: 'smooth' }); }
    } else if (target.matches('[data-installation-confirm]')) {
      event.preventDefault(); if (busy || !job) return;
      const result = await run(signal => installationRequest<Job>('confirm', { job_id: job!.job_id, action_ids: new FormData(target).getAll('action_id') }, signal));
      if (result) { job = result; redraw(); }
    }
  };
  const onClick = async (event: Event) => {
    const action = (event.target as Element).closest<HTMLElement>('[data-installation-action]')?.dataset.installationAction;
    if (!action || busy) return;
    if (action === 'rollback-review') { query('[data-installation-rollback]').removeAttribute('hidden'); return; }
    if (action === 'save-token') {
      if (!token.value.trim()) { message('Enter the Cloudflare API token.', true); return; }
      const reference = await run(signal => saveDnsCredential(token.value.trim(), signal));
      token.value = '';
      if (reference) {
        query<HTMLDetailsElement>('[data-installation-credential]').open = false;
        if (timer) clearTimeout(timer);
        await refresh();
        if (!disposed) query<HTMLSelectElement>('[name=dns_secret_ref]').value = reference;
      }
    } else if (action === 'verify') {
      const result = await run(signal => installationRequest<{ verification: Verification }>('verify', undefined, signal));
      if (result) query('[data-installation-verification]').innerHTML = verificationHtml(result.verification);
    } else if (action === 'apply' && plan) {
      const result = await run(signal => installationRequest<Job>('apply', { plan_id: plan!.plan_id }, signal));
      if (result) { job = result; jobPlan = plan; plan = undefined; redraw(); if (timer) clearTimeout(timer); void refresh(); }
    } else if (['retry', 'rollback'].includes(action) && job) {
      const result = await run(signal => installationRequest<Job>(action, { job_id: job!.job_id }, signal));
      if (result) { job = result; redraw(); if (timer) clearTimeout(timer); void refresh(); }
    }
  };
  const onInput = (event: Event) => { if ((event.target as Element).closest('[data-installation-form]')) { plan = undefined; redraw(); } };
  const onChange = (event: Event) => onInput(event);
  root.addEventListener('change', onChange);
  root.addEventListener('submit', onSubmit); root.addEventListener('click', onClick); root.addEventListener('input', onInput);
  void refresh(true);
  return { destroy() { disposed = true; if (timer) clearTimeout(timer); requests.forEach(controller => controller.abort()); token.value = ''; root.replaceChildren(); root.removeEventListener('submit', onSubmit); root.removeEventListener('click', onClick); root.removeEventListener('input', onInput); root.removeEventListener('change', onChange); } };
}
