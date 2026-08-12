import { escapeHtml } from './html';

export type SettingsNotice = { tone: 'info' | 'success' | 'error'; message: string };

export function noticeHtml(notice: SettingsNotice | null) {
  if (!notice) return '';
  return `<div class="settings-notice settings-notice-${notice.tone}">
    <span class="material-symbols-rounded" aria-hidden="true">${notice.tone === 'error' ? 'error' : notice.tone === 'success' ? 'task_alt' : 'info'}</span>
    <span>${escapeHtml(notice.message)}</span>
    <button type="button" class="settings-icon-button" id="dismiss-notice" aria-label="Close">
      <span class="material-symbols-rounded" aria-hidden="true">close</span>
    </button>
  </div>`;
}
