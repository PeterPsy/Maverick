import type { LearningView, LearningSettings } from './learningController';
import type { ProviderModelOption } from './adminApi';
import { escapeHtml as e } from './html';

export function learningControlsHtml(state: LearningView, models: ProviderModelOption[]): string {
  const c = { ...state.data!.settings, ...state.draftSettings };
  const disabled = state.saving ? 'disabled' : '';
  const dependency = state.dependency?.dependencies.find((item) => item.alias === 'learning-memory');
  const selected = dependency?.selected_provider_app_ids[0] || '';
  const toggle = (key: keyof LearningSettings, label: string, description: string, icon?: string) => `<label class="learning-toggle ${icon ? 'learning-channel' : ''}">
    ${icon ? `<span class="material-symbols-rounded learning-channel-icon" aria-hidden="true">${icon}</span>` : ''}
    <span class="learning-toggle-copy"><strong>${label}</strong><small>${description}</small></span>
    <input type="checkbox" role="switch" name="${key}" ${c[key] ? 'checked' : ''} ${disabled}><span class="learning-toggle-track" aria-hidden="true"></span></label>`;
  const number = (key: keyof LearningSettings, label: string, min: number, max: number, hint: string) => `<label>${label}<input type="number" name="${key}" min="${min}" max="${max}" value="${c[key]}" required ${disabled}><small>${hint}</small></label>`;
  return `<form id="learning-settings" class="settings-card learning-controls" aria-busy="${state.saving}">
    <div class="learning-section-heading"><div><h3>Automatic learning</h3><p>Learn lasting knowledge and new Maverick improvements from completed work.</p></div><span class="settings-pill">One analysis at a time</span></div>
    ${toggle('enabled', 'Enable learning', 'Review conversations after a quiet period. Unfinished work stays under observation.')}
    <div class="learning-channel-grid">
      ${toggle('memory_enabled', 'Memory', 'Keep sourced discoveries, people, events and lasting knowledge.', 'neurology')}
      ${toggle('improvements_enabled', 'Improvements', 'Find general limits of Maverick; skip work already requested or underway.', 'lightbulb')}
    </div>
    <div class="learning-form-grid" id="learning-memory-options" ${c.memory_enabled ? '' : 'hidden'}>
      <label>Save to<select name="memory_provider" ${disabled}><option value="">Choose a Memory provider</option>${dependency?.candidates.map((p) => `<option value="${e(p.app_id)}" ${p.app_id === selected ? 'selected' : ''}>${e(p.name)}</option>`).join('') || ''}</select><small id="learning-provider-hint">${selected ? 'Facts and their chat evidence are saved to this app.' : 'Choose a provider to check existing knowledge and save facts.'}</small></label>
      <label>Saving mode<select name="memory_mode" ${disabled}><option value="review" ${c.memory_mode === 'review' ? 'selected' : ''}>Review before saving</option><option value="automatic" ${c.memory_mode === 'automatic' ? 'selected' : ''}>Save supported explicit facts automatically</option></select><small id="learning-mode-hint">${c.memory_mode === 'automatic' ? 'Only explicit user facts with verified quotes and no Memory matches are saved automatically.' : 'You approve each fact before it enters Memory.'}</small></label>
    </div>
    <p class="learning-note">A quiet chat is not necessarily finished. Proposals require a completed work episode; development instructions do not become Memory.</p>
    <details class="learning-advanced" data-learning-disclosure="timing" ${state.openSections?.includes('timing') ? 'open' : ''}>
      <summary><span><strong>Timing &amp; model</strong><small>${c.idle_seconds} seconds after the last response · ${c.model_source === 'workspace' ? 'Workspace Codex' : 'Fast API model'}</small></span><span class="material-symbols-rounded" aria-hidden="true">expand_more</span></summary>
      <div class="learning-form-grid">
        ${number('idle_seconds', 'Quiet period (seconds)', 0, 3600, 'Delay before review. New messages postpone it; this delay does not certify that work is finished.')}
        <label>Analysis model<select name="model_source" ${disabled}><option value="workspace" ${c.model_source === 'workspace' ? 'selected' : ''}>Workspace Codex</option><option value="fast_model" ${c.model_source === 'fast_model' ? 'selected' : ''}>Configured fast API model</option></select><small>API mode uses the fast model configured in platform settings.</small></label>
        <label data-learning-native ${c.model_source === 'workspace' ? '' : 'hidden'}>Codex model<select name="model_id" ${disabled}><option value="">Workspace default</option>${models.map((m) => `<option value="${e(m.model_id)}" ${m.model_id === c.model_id ? 'selected' : ''}>${e(m.label || m.model_id)}</option>`).join('')}${c.model_id && !models.some((m) => m.model_id === c.model_id) ? `<option selected value="${e(c.model_id)}">${e(c.model_id)} (unavailable)</option>` : ''}</select></label>
        <label data-learning-native ${c.model_source === 'workspace' ? '' : 'hidden'}>Reasoning<select name="reasoning_effort" ${disabled}>${['low', 'medium', 'high'].map((x) => `<option value="${x}" ${c.reasoning_effort === x ? 'selected' : ''}>${{low:'Low · faster',medium:'Medium',high:'High · more thorough'}[x]}</option>`).join('')}</select></label>
      </div>
    </details>
    <details class="learning-advanced" data-learning-disclosure="limits" ${state.openSections?.includes('limits') ? 'open' : ''}>
      <summary><span><strong>Usage &amp; retention</strong><small>${c.daily_token_budget.toLocaleString()} tokens per day · ${c.retention_days} days of transcripts</small></span><span class="material-symbols-rounded" aria-hidden="true">expand_more</span></summary>
      <div class="learning-form-grid">
        ${number('daily_token_budget', 'Daily token allowance', 1000, 10000000, 'UTC day. Each analysis reserves tokens before it starts.')}
        ${number('max_context_chars', 'Context limit (characters)', 4000, 60000, 'Maximum conversation evidence per analysis.')}
        ${number('max_output_tokens', 'Output limit (tokens)', 128, 8192, 'Maximum size of the generated suggestions.')}
        ${number('timeout_seconds', 'Timeout (seconds)', 10, 300, 'Stop an analysis if it takes too long.')}
        ${number('retention_days', 'Transcript retention (days)', 1, 365, 'Saved Memory facts and review decisions remain available.')}
        <label>Parallel improvement agents<input type="number" name="improvement_concurrency" min="1" max="8" value="${c.improvement_concurrency ?? 4}" required ${disabled}><small>Up to this many improvement chats run together. Memory always runs one chat at a time.</small></label>
      </div>
    </details>
    <details class="learning-advanced" data-learning-disclosure="scope" ${state.openSections?.includes('scope') ? 'open' : ''}>
      <summary><span><strong>Exclusions &amp; instructions</strong><small>${c.excluded_thread_ids.length + c.excluded_project_ids.length ? `${c.excluded_thread_ids.length + c.excluded_project_ids.length} exclusions` : 'All eligible chats'} · optional guidance</small></span><span class="material-symbols-rounded" aria-hidden="true">expand_more</span></summary>
      <div class="learning-form-grid">
        <label>Excluded chat IDs<textarea name="excluded_thread_ids" rows="2" ${disabled}>${e(c.excluded_thread_ids.join('\n'))}</textarea><small>One ID per line. The ID is the last part of a chat URL.</small></label>
        <label>Excluded project IDs<textarea name="excluded_project_ids" rows="2" ${disabled}>${e(c.excluded_project_ids.join('\n'))}</textarea><small>One ID per line. Chats in these projects are skipped.</small></label>
        <label class="learning-wide">Additional guidance<textarea name="instructions" rows="3" maxlength="4000" placeholder="For example: focus on tool failures, missing capabilities and sourced discoveries…" ${disabled}>${e(c.instructions)}</textarea></label>
      </div>
    </details>
    <div class="learning-save-bar"><span id="learning-draft-status" role="status">${state.dirty ? 'Unsaved changes' : state.notice || 'Settings are up to date'}</span><div class="learning-actions"><button type="button" class="settings-secondary" id="learning-discard" ${state.dirty && !state.saving ? '' : 'disabled'}>Discard edits</button><button class="settings-primary" type="submit" ${disabled}>${state.saving ? 'Saving…' : 'Save settings'}</button></div></div>
  </form>`;
}
