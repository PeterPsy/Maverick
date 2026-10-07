import type { LearningView } from './learningController';
import type { ProviderModelOption } from './adminApi';
import { escapeHtml as e } from './html';
import { learningControlsHtml } from './learningControls';
import { date, statusLabel } from './learningResults';
import { learningTicketsHtml } from './learningTickets';

export function learningPageHtml(state: LearningView, models: ProviderModelOption[] = []): string {
  const { data, error, saving } = state;
  if (!data) return `<section class="settings-card learning-empty"><strong>${state.loading ? 'Loading learning settings…' : 'Learning is unavailable'}</strong>${error ? `<p role="alert">${e(error)}</p>` : ''}<button class="settings-secondary" id="learning-refresh">Retry</button></section>`;
  const c = data.settings;
  const counts = data.counts || { pending_memory: data.items.filter((x) => x.kind === 'memory' && x.status === 'pending').length,
    pending_improvements: data.items.filter((x) => x.kind === 'improvement' && x.status === 'pending').length,
    queued: data.jobs.filter((x) => x.status === 'queued').length, running: data.jobs.filter((x) => x.status === 'running').length, failed: data.jobs.filter((x) => x.status === 'failed').length, budget_waiting: 0 };
  const status = !c.enabled ? 'Off' : c.paused ? 'Paused' : !c.memory_enabled && !c.improvements_enabled ? 'No outputs selected' : counts.running ? 'Analyzing' : 'On';
  const description = !c.enabled ? 'Enable learning to capture future conversations.' : c.paused ? 'Chats are still captured. Resume when you are ready.' : !c.memory_enabled && !c.improvements_enabled ? 'Choose Memory or Improvements to start analysis.' : counts.running ? 'One conversation is being reviewed. The others wait in the queue.' : 'Quiet periods trigger review. Only completed work can produce proposals.';
  const tokens = data.daily_tokens_reserved_or_used;
  const percent = Math.min(100, Math.round(tokens / c.daily_token_budget * 100));
  const disabled = saving ? 'disabled' : '';
  const selectedLabel = (id: string) => data.conversations.find((x) => x.session_id === id)?.label || `Chat ${id.slice(0, 8)}`;
  const tabCount = { memory: counts.open_memory ?? counts.pending_memory, improvements: counts.open_improvement ?? counts.pending_improvements, analyses: counts.queued + counts.running, audit: 0 };
  return `<section class="settings-card learning-overview">
    <div class="learning-status-row"><div class="learning-status-copy"><span class="learning-status-dot ${c.enabled && !c.paused ? 'is-on' : ''}" aria-hidden="true"></span><div><h3>Learning is ${status.toLowerCase()}</h3><p>${description}</p></div></div><div class="learning-actions">${c.enabled ? `<button id="learning-pause" class="settings-secondary" ${disabled}>${c.paused ? 'Resume analysis' : 'Pause analysis'}</button>` : ''}<button id="learning-refresh" class="learning-icon-button" aria-label="Refresh learning status" ${disabled}><span class="material-symbols-rounded" aria-hidden="true">refresh</span></button></div></div>
    <div class="learning-stats"><div><strong>${counts.pending_memory + counts.pending_improvements}</strong><span>To review</span></div><div><strong>${counts.queued}</strong><span>In queue</span></div><div class="learning-usage"><div><span>Today’s token allowance</span><strong>${percent}%</strong></div><progress value="${Math.min(tokens, c.daily_token_budget)}" max="${c.daily_token_budget}" aria-label="Daily learning token allowance"></progress><small>${tokens.toLocaleString()} / ${c.daily_token_budget.toLocaleString()} reserved or observed · resets at 00:00 UTC</small></div></div>
    ${tokens >= c.daily_token_budget ? '<p class="learning-notice">Today’s allowance is reached. New analyses wait until the next UTC day or a higher saved allowance.</p>' : ''}
    ${counts.budget_waiting && tokens < c.daily_token_budget ? '<p class="learning-notice">The remaining allowance cannot cover the next analysis. Increase it in Usage &amp; retention or wait for the UTC reset. Codex reserves extra tokens for its instructions.</p>' : ''}
    ${counts.failed ? `<p class="learning-notice">${counts.failed} failed ${counts.failed === 1 ? 'analysis' : 'analyses'}. Open the Analyses tab to inspect or retry.</p>` : ''}
    ${error ? `<p class="learning-error" role="alert">${e(error)}</p>` : ''}
  </section>
  ${learningControlsHtml(state, models)}
  <section class="settings-card learning-results">
    <div class="learning-section-heading"><div><h3>Results &amp; history</h3><p>Review suggestions and see what the agent has done.</p></div></div>
    <div class="learning-manual"><label for="learning-session">Analyze a captured chat</label><div class="learning-actions"><select id="learning-session" ${!data.conversations.length || saving ? 'disabled' : ''}><option value="">${data.conversations.length ? 'Choose a conversation…' : 'No captured conversations yet'}</option>${data.conversations.map((x) => `<option value="${e(x.session_id)}" ${state.selectedSession === x.session_id ? 'selected' : ''}>${e(selectedLabel(x.session_id))}</option>`).join('')}</select><button id="learning-analyze" class="settings-secondary" ${saving || !c.enabled || c.paused || !state.selectedSession || (!c.memory_enabled && !c.improvements_enabled) ? 'disabled' : ''}>Analyze now</button></div><p class="learning-note">${!c.enabled ? 'Enable learning first. Only conversations captured after activation are available.' : c.paused ? 'Resume analysis to use the queue.' : 'Adds new captured messages to the same serial queue; active chats wait until ready.'}</p></div>
    <div class="learning-tabs" role="tablist" aria-label="Learning results">${(['memory', 'improvements', 'analyses', 'audit'] as const).map((x) => `<button id="learning-tab-${x}" role="tab" aria-controls="learning-panel" aria-selected="${state.tab === x}" tabindex="${state.tab === x ? '0' : '-1'}" class="${state.tab === x ? 'is-active' : ''}" data-learning-tab="${x}">${{memory:'Memory',improvements:'Improvements',analyses:'Analyses',audit:'Activity'}[x]}${tabCount[x] ? `<span>${tabCount[x]}</span>` : ''}</button>`).join('')}</div>
    <div id="learning-panel" role="tabpanel" aria-labelledby="learning-tab-${state.tab}" tabindex="0">
    ${state.tab === 'improvements' || state.tab === 'memory' ? learningTicketsHtml(state) : ''}
    ${state.tab === 'analyses' ? `<div class="learning-list">${data.jobs.map((job) => `<article class="learning-row"><div><div class="learning-item-heading"><strong>${e(selectedLabel(job.session_id))}</strong><span class="settings-pill">${e(statusLabel(job.status))}</span></div><p>${date(job.created_at)} · ${job.attempts} attempt(s) · ${job.usage || job.reserved} tokens${job.model ? ` · ${e(job.model)}` : ''}</p>${job.error ? `<p class="learning-error">${e(job.error)}</p>` : ''}</div><div class="learning-actions"><button class="settings-secondary" data-learning-job="${e(job.id)}" data-learning-command="inspect">Details</button>${['queued','running'].includes(job.status) ? `<button class="settings-secondary" data-learning-job="${e(job.id)}" data-learning-command="cancel" ${disabled}>Cancel</button>` : ['failed','cancelled'].includes(job.status) ? `<button class="settings-secondary" data-learning-job="${e(job.id)}" data-learning-command="retry" ${disabled}>Retry</button>` : ''}</div></article>`).join('') || '<div class="learning-empty"><strong>No analyses yet</strong><p>After activation, finish a chat and wait for the quiet period. Its analysis will appear here.</p></div>'}</div>` : ''}
    ${state.tab === 'audit' ? `<div class="learning-list">${data.audit.map((x) => `<div class="learning-row"><span>${e(x.action.replaceAll('.', ' · ').replaceAll('_', ' '))}</span><small>${date(x.created_at)} · ${e(x.actor)}</small></div>`).join('') || '<div class="learning-empty"><strong>No activity yet</strong><p>Settings changes and review decisions will appear here.</p></div>'}</div>` : ''}
    ${state.detail ? `<details class="learning-transcript" open><summary>Analysis details · ${e(state.detail.id)}</summary><h4>Conversation evidence</h4><pre>${e(JSON.stringify(state.detail.input, null, 2))}</pre><h4>Agent result</h4><pre>${e(state.detail.output_text || 'No output available. The run may be pending or its transcript retention period has ended.')}</pre></details>` : ''}
    </div>
  </section>`;
}
