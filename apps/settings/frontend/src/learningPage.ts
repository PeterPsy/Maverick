import type { LearningItem, LearningView } from './learningController';
import type { ProviderModelOption } from './adminApi';
import { escapeHtml as e } from './html';

export function learningPageHtml(state: LearningView, models: ProviderModelOption[] = []): string {
  const { data, error, saving } = state;
  if (!data) return `<section class="settings-card"><p>${state.loading ? 'Loading learning settings…' : 'Learning is unavailable.'}</p>${error ? `<p role="alert">${e(error)}</p>` : ''}<button class="settings-secondary" id="learning-refresh">Retry</button></section>`;
  const c = data.settings;
  const disabled = saving ? 'disabled' : '';
  const dependency = state.dependency?.dependencies.find((item) => item.alias === 'learning-memory');
  const selected = dependency?.selected_provider_app_ids[0] || '';
  const checkbox = (key: keyof typeof c, label: string) => `<label class="learning-switch"><input type="checkbox" name="${key}" ${c[key] ? 'checked' : ''} ${disabled}>${label}</label>`;
  const number = (key: keyof typeof c, label: string, min: number, max: number) => `<label>${label}<input type="number" name="${key}" min="${min}" max="${max}" value="${c[key]}" required ${disabled}></label>`;
  return `<section class="settings-card learning-controls">
    <div class="settings-heading"><h3>Conversation learning</h3><span class="settings-pill">1 analysis at a time</span></div>
    <form id="learning-settings">
      <div class="learning-switches">${checkbox('enabled', 'Enable learning')}${checkbox('paused', 'Pause analysis')}${checkbox('memory_enabled', 'Memory candidates')}${checkbox('improvements_enabled', 'Improvement proposals')}</div>
      <div class="learning-form-grid">
        <label>Memory mode<select name="memory_mode" ${disabled}><option value="review" ${c.memory_mode === 'review' ? 'selected' : ''}>Review before saving</option><option value="automatic" ${c.memory_mode === 'automatic' ? 'selected' : ''}>Save explicit supported facts automatically</option></select></label>
        <label>Memory provider<select name="memory_provider" ${disabled}><option value="">Choose provider</option>${dependency?.candidates.map((p) => `<option value="${e(p.app_id)}" ${p.app_id === selected ? 'selected' : ''}>${e(p.name)}</option>`).join('') || ''}</select></label>
        <label>Analysis model source<select name="model_source" ${disabled}><option value="workspace" ${c.model_source === 'workspace' ? 'selected' : ''}>Workspace Codex model</option><option value="fast_model" ${c.model_source === 'fast_model' ? 'selected' : ''}>Configured fast API model</option></select></label>
        <label>Codex model<select name="model_id" ${disabled}><option value="">Workspace default</option>${models.map((m) => `<option value="${e(m.model_id)}" ${m.model_id === c.model_id ? 'selected' : ''}>${e(m.label || m.model_id)}</option>`).join('')}${c.model_id && !models.some((m) => m.model_id === c.model_id) ? `<option selected value="${e(c.model_id)}">${e(c.model_id)} (unavailable)</option>` : ''}</select></label>
        <label>Reasoning<select name="reasoning_effort" ${disabled}>${['low', 'medium', 'high'].map((x) => `<option ${c.reasoning_effort === x ? 'selected' : ''}>${x}</option>`).join('')}</select></label>
        ${number('idle_seconds', 'Wait after last response (seconds)', 0, 3600)}
        ${number('daily_token_budget', 'Daily token allowance', 1000, 10000000)}
        ${number('max_context_chars', 'Context character limit', 4000, 60000)}
        ${number('max_output_tokens', 'Output token allowance', 128, 8192)}
        ${number('timeout_seconds', 'Analysis timeout (seconds)', 10, 300)}
        ${number('retention_days', 'Run transcript retention (days)', 1, 365)}
        <label>Excluded chat IDs<textarea name="excluded_thread_ids" rows="2" ${disabled}>${e(c.excluded_thread_ids.join('\n'))}</textarea></label>
        <label>Excluded project IDs<textarea name="excluded_project_ids" rows="2" ${disabled}>${e(c.excluded_project_ids.join('\n'))}</textarea></label>
        <label class="learning-wide">Additional analysis instructions<textarea name="instructions" rows="3" maxlength="4000" ${disabled}>${e(c.instructions)}</textarea></label>
      </div>
      <p class="learning-note">Automatic saving is limited to explicit user facts with verified evidence and no Memory match. Improvements remain proposals. API inference uses your configured fast model. Native usage is reconciled after each run.</p>
      <div class="learning-actions"><button class="settings-primary" type="submit" ${disabled}>${saving ? 'Saving…' : 'Save settings'}</button><button class="settings-secondary" type="button" id="learning-refresh" ${disabled}>Refresh</button><span>${data.daily_tokens_reserved_or_used.toLocaleString()} / ${c.daily_token_budget.toLocaleString()} tokens reserved or observed today</span></div>
    </form>
    ${error ? `<p class="learning-error" role="alert">${e(error)}</p>` : ''}
  </section>
  <section class="settings-card learning-results">
    <div class="learning-actions"><select id="learning-session" aria-label="Chat to analyze">${data.conversations.map((x) => `<option value="${e(x.session_id)}">${e(x.session_id)}${x.project_id ? ` · ${e(x.project_id)}` : ''}</option>`).join('')}</select><button id="learning-analyze" class="settings-secondary" ${disabled || !c.enabled || c.paused || !data.conversations.length ? 'disabled' : ''}>Analyze now</button></div>
    <div class="learning-tabs" role="tablist" aria-label="Learning results">${(['memory', 'improvements', 'analyses', 'audit'] as const).map((x) => `<button role="tab" aria-selected="${state.tab === x}" class="settings-secondary ${state.tab === x ? 'is-active' : ''}" data-learning-tab="${x}">${{memory:'Memory',improvements:'Improvements',analyses:'Analyses',audit:'Activity'}[x]}</button>`).join('')}</div>
    ${state.tab === 'memory' || state.tab === 'improvements' ? itemList(data.items.filter((x) => x.kind === (state.tab === 'memory' ? 'memory' : 'improvement')), saving) : ''}
    ${state.tab === 'analyses' ? `<div class="learning-list">${data.jobs.map((job) => `<article class="learning-row"><div><strong>${e(job.status)}</strong> · ${date(job.created_at)}<p>${e(job.session_id)} · ${job.attempts} attempt(s) · ${job.usage || job.reserved} tokens${job.model ? ` · ${e(job.model)}` : ''}</p>${job.error ? `<p class="learning-error">${e(job.error)}</p>` : ''}</div><div class="learning-actions"><button class="settings-secondary" data-learning-job="${e(job.id)}" data-learning-command="inspect">Transcript</button>${['queued','running'].includes(job.status) ? `<button class="settings-secondary" data-learning-job="${e(job.id)}" data-learning-command="cancel" ${disabled}>Cancel</button>` : ['failed','cancelled'].includes(job.status) ? `<button class="settings-secondary" data-learning-job="${e(job.id)}" data-learning-command="retry" ${disabled}>Retry</button>` : ''}</div></article>`).join('') || '<p>No analyses yet. Enable learning to capture future conversations.</p>'}</div>` : ''}
    ${state.tab === 'audit' ? `<div class="learning-list">${data.audit.map((x) => `<div class="learning-row"><span>${e(x.action)} · ${e(x.target)}</span><small>${date(x.created_at)} · ${e(x.actor)}</small></div>`).join('') || '<p>No activity yet.</p>'}</div>` : ''}
    ${state.detail ? `<details class="learning-transcript" open><summary>Analysis transcript · ${e(state.detail.id)}</summary><h4>Conversation evidence</h4><pre>${e(JSON.stringify(state.detail.input, null, 2))}</pre><h4>Agent result</h4><pre>${e(state.detail.output_text || 'No completed output')}</pre></details>` : ''}
  </section>`;
}

function itemList(items: LearningItem[], saving: boolean) {
  if (!items.length) return '<p>No candidates yet.</p>';
  return `<div class="learning-list">${items.map((item) => {
    const busy = saving || ['checking', 'saving', 'undoing'].includes(item.status);
    const button = (command: string, label: string) => `<button class="settings-secondary" data-learning-item="${e(item.id)}" data-learning-command="${command}" ${busy ? 'disabled' : ''}>${label}</button>`;
    const matches = item.details.memory_matches || [];
    return `<article class="learning-row learning-item"><div class="learning-item-heading"><strong>${e(item.title)}</strong><span class="settings-pill">${e(item.status)}${item.occurrences > 1 ? ` · ${item.occurrences} observations` : ''}</span></div><p>${e(item.body)}</p>
    ${item.kind === 'improvement' ? `<dl class="learning-proposal-details">${(['category','expected_impact','effort','verification'] as const).filter((key) => item.details[key]).map((key) => `<dt>${{category:'Category',expected_impact:'Expected impact',effort:'Effort',verification:'Verification'}[key]}</dt><dd>${e(item.details[key] || '')}</dd>`).join('')}</dl>` : ''}
    ${item.details.memory_check_error || item.details.save_error ? `<p class="learning-error">${e(item.details.save_error || item.details.memory_check_error || '')}</p>` : ''}
    <details><summary>Evidence${matches.length ? ' and Memory matches' : ''}</summary>${item.evidence.map((x) => `<blockquote><p>${e(x.quote)}</p><small>${e(x.role)} · ${e(x.turn_id)} · <a href="/app/chat/threads/${encodeURIComponent(x.session_id)}">Open chat</a>${typeof x.metrics.duration_seconds === 'number' ? ` · ${x.metrics.duration_seconds.toFixed(1)} s` : ''}</small></blockquote>`).join('')}${matches.length ? `<p>Related Memory: ${matches.map((x) => e(x.title)).join(', ')}. Choose a matching node to attach evidence, or explicitly create a separate fact.</p>` : ''}</details>
    ${item.status === 'pending' ? `<details><summary>Edit candidate</summary><label>Title<input data-learning-title="${e(item.id)}" value="${e(item.title)}" maxlength="240"></label><label>Description<textarea data-learning-body="${e(item.id)}" rows="3" maxlength="4000">${e(item.body)}</textarea></label>${button('edit', 'Save edit')}</details>` : ''}
    <div class="learning-actions">${item.status === 'pending' ? (item.kind === 'memory' ? `${matches.length ? `<select data-learning-target="${e(item.id)}" aria-label="Memory destination"><option value="">Choose destination</option>${matches.map((x) => `<option value="${e(x.id)}">Attach to ${e(x.title)}</option>`).join('')}<option value="new">Create separate fact</option></select>` : ''}${button('approve', 'Save to Memory')}` : button('accept', 'Accept proposal')) + button('reject', 'Reject') : ''}${item.status === 'accepted' ? button('implemented', 'Mark implemented') + button('reject', 'Reject') : ''}${item.status === 'saved' ? `<a class="settings-secondary" href="/app/${encodeURIComponent(item.provider_id || 'memory')}/nodes/${encodeURIComponent(item.node_id)}">Open Memory</a>${item.details.node_created ? button('undo', 'Undo save') : ''}` : ''}</div></article>`;
  }).join('')}</div>`;
}

function date(timestamp: number) { return e(new Date(timestamp * 1000).toLocaleString()); }
