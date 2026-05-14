import type { SettingsPage } from './pages';
import { escapeHtml } from './html';

export function pageSettingsBlockHtml(page: SettingsPage) {
  return `<section class="settings-card settings-page-settings">
    <span class="settings-page-settings-icon material-symbols-rounded" aria-hidden="true">${escapeHtml(page.icon)}</span>
    <span>
      <p class="settings-kicker">Settings page</p>
      <h2>${escapeHtml(page.title)}</h2>
      <p class="settings-card-copy">${escapeHtml(page.summary)}</p>
    </span>
  </section>`;
}
