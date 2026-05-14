import type { SettingsPage } from './pages';

const USER_FORM_FIELD_COUNT = 5;
const PROFILE_FIELD_COUNT = 4;
const MEMBERSHIP_ROW_COUNT = 4;
const WORKSPACE_APP_ROW_COUNT = 3;
const SETTINGS_TILE_COUNT = 2;
const RUNTIME_ROW_COUNT = 4;

export function settingsAppSkeletonHtml(page: SettingsPage): string {
  return `<section class="settings-loading-skeleton" role="status" aria-label="Settings content is loading">
    <header class="detail-header settings-loading-skeleton__header" aria-hidden="true">
      <div class="detail-title-block">
        ${lineHtml('title')}
        <span class="detail-title-separator" aria-hidden="true"></span>
        ${lineHtml('subtitle')}
      </div>
    </header>
    ${activePageSkeletonHtml(page)}
  </section>`;
}

function activePageSkeletonHtml(page: SettingsPage): string {
  if (page.id === 'workspace-access') {
    return workspaceAccessSkeletonHtml();
  }
  if (page.id === 'workspace-apps') {
    return workspaceAppsSkeletonHtml();
  }
  if (page.id === 'platform-settings') {
    return platformSettingsSkeletonHtml();
  }
  if (page.id === 'persistence') {
    return persistenceSkeletonHtml();
  }
  return usersSkeletonHtml();
}

function usersSkeletonHtml(): string {
  return `${pageSettingsSkeletonHtml()}
    <section class="settings-card settings-loading-skeleton__create" aria-hidden="true">
      ${stackHtml('short-title')}
      ${repeatHtml(USER_FORM_FIELD_COUNT, () => blockHtml('field'))}
      ${blockHtml('button')}
    </section>
    ${userPickerSkeletonHtml()}
    <div class="settings-loading-skeleton__profile-row" aria-hidden="true">
      <section class="settings-card settings-loading-skeleton__detail-card">
        ${headingSkeletonHtml(true)}
        <div class="settings-loading-skeleton__field-grid">
          ${repeatHtml(PROFILE_FIELD_COUNT, () => labelFieldSkeletonHtml())}
        </div>
        ${blockHtml('toggle')}
        ${blockHtml('button')}
      </section>
      <section class="settings-card settings-loading-skeleton__password-card">
        ${headingSkeletonHtml(false)}
        ${lineHtml('copy')}
        <div class="settings-loading-skeleton__field-grid">
          ${repeatHtml(2, () => labelFieldSkeletonHtml())}
        </div>
        ${blockHtml('button')}
        ${blockHtml('danger-button')}
      </section>
    </div>`;
}

function workspaceAccessSkeletonHtml(): string {
  return `${pageSettingsSkeletonHtml()}
    ${userPickerSkeletonHtml()}
    <section class="settings-card" aria-hidden="true">
      ${headingSkeletonHtml(true)}
      <div class="settings-loading-skeleton__rows">
        ${repeatHtml(MEMBERSHIP_ROW_COUNT, () => membershipRowSkeletonHtml())}
      </div>
    </section>`;
}

function workspaceAppsSkeletonHtml(): string {
  return `${pageSettingsSkeletonHtml()}
    <section class="settings-card" aria-hidden="true">
      ${headingSkeletonHtml(false)}
      ${lineHtml('copy-wide')}
      <div class="settings-loading-skeleton__rows">
        ${repeatHtml(WORKSPACE_APP_ROW_COUNT, () => workspaceAppRowSkeletonHtml())}
      </div>
    </section>`;
}

function platformSettingsSkeletonHtml(): string {
  return `${pageSettingsSkeletonHtml()}
    <section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      ${headingSkeletonHtml(false)}
      <div class="settings-loading-skeleton__settings-grid">
        ${repeatHtml(SETTINGS_TILE_COUNT, () => settingsTileSkeletonHtml())}
      </div>
      <div class="settings-loading-skeleton__provider-form">
        ${repeatHtml(2, () => labelFieldSkeletonHtml())}
        ${blockHtml('button')}
      </div>
      <div class="settings-loading-skeleton__runtime-list">
        ${repeatHtml(RUNTIME_ROW_COUNT, () => runtimeRowSkeletonHtml())}
      </div>
    </section>`;
}

function persistenceSkeletonHtml(): string {
  return `${pageSettingsSkeletonHtml()}
    <section class="settings-card settings-loading-skeleton__persistence" aria-hidden="true">
      ${headingSkeletonHtml(true)}
      <div class="settings-loading-skeleton__adapter-cards">
        ${repeatHtml(2, () => adapterCardSkeletonHtml())}
      </div>
      ${resultSkeletonHtml()}
    </section>`;
}

function pageSettingsSkeletonHtml(): string {
  return `<section class="settings-card settings-page-settings" aria-hidden="true">
    ${iconHtml('page')}
    <span class="settings-loading-skeleton__copy-stack">
      ${lineHtml('kicker')}
      ${lineHtml('card-title')}
      ${lineHtml('copy')}
    </span>
  </section>`;
}

function userPickerSkeletonHtml(): string {
  return `<section class="settings-card settings-user-picker" aria-hidden="true">
    <div class="settings-loading-skeleton__copy-stack">
      ${lineHtml('kicker')}
      ${lineHtml('card-title')}
      ${lineHtml('copy-short')}
    </div>
    ${labelFieldSkeletonHtml()}
  </section>`;
}

function headingSkeletonHtml(withPill: boolean): string {
  return `<div class="settings-loading-skeleton__heading">
    <span class="settings-loading-skeleton__copy-stack">
      ${lineHtml('kicker')}
      ${lineHtml('card-title')}
    </span>
    ${withPill ? blockHtml('pill') : ''}
  </div>`;
}

function stackHtml(titleSize: 'short-title'): string {
  return `<div class="settings-loading-skeleton__copy-stack">
    ${lineHtml('kicker')}
    ${lineHtml(titleSize)}
  </div>`;
}

function labelFieldSkeletonHtml(): string {
  return `<span class="settings-loading-skeleton__field-wrap">
    ${lineHtml('label')}
    ${blockHtml('field')}
  </span>`;
}

function membershipRowSkeletonHtml(): string {
  return `<span class="settings-loading-skeleton__row settings-loading-skeleton__row--membership">
    ${blockHtml('checkbox')}
    ${iconHtml('row')}
    <span class="settings-loading-skeleton__copy-stack">
      ${lineHtml('row-title')}
      ${lineHtml('row-copy')}
    </span>
    ${blockHtml('select')}
  </span>`;
}

function workspaceAppRowSkeletonHtml(): string {
  return `<span class="settings-loading-skeleton__row settings-loading-skeleton__row--app">
    ${iconHtml('row')}
    <span class="settings-loading-skeleton__copy-stack">
      ${lineHtml('row-title')}
      ${lineHtml('row-copy')}
    </span>
    ${blockHtml('toggle-pill')}
    ${blockHtml('button')}
  </span>`;
}

function settingsTileSkeletonHtml(): string {
  return `<span class="settings-loading-skeleton__row settings-loading-skeleton__row--tile">
    ${iconHtml('row')}
    <span class="settings-loading-skeleton__copy-stack">
      ${lineHtml('row-title')}
      ${lineHtml('row-copy')}
    </span>
  </span>`;
}

function runtimeRowSkeletonHtml(): string {
  return `<span class="settings-loading-skeleton__row settings-loading-skeleton__row--runtime">
    ${iconHtml('row')}
    <span class="settings-loading-skeleton__copy-stack">
      ${lineHtml('row-title')}
      ${lineHtml('row-copy')}
    </span>
    ${blockHtml('button')}
  </span>`;
}

function adapterCardSkeletonHtml(): string {
  return `<span class="settings-loading-skeleton__adapter-card">
    ${iconHtml('row')}
    <span class="settings-loading-skeleton__copy-stack">
      ${lineHtml('row-title')}
      ${lineHtml('row-copy-wide')}
    </span>
    ${blockHtml('pill')}
  </span>`;
}

function resultSkeletonHtml(): string {
  return `<span class="settings-loading-skeleton__result">
    ${iconHtml('row')}
    <span class="settings-loading-skeleton__copy-stack">
      ${lineHtml('row-title')}
      ${lineHtml('row-copy-wide')}
    </span>
  </span>`;
}

function lineHtml(size: string): string {
  return `<span class="settings-loading-skeleton__line settings-loading-skeleton__line--${size}"></span>`;
}

function blockHtml(size: string): string {
  return `<span class="settings-loading-skeleton__block settings-loading-skeleton__block--${size}"></span>`;
}

function iconHtml(size: string): string {
  return `<span class="settings-loading-skeleton__icon settings-loading-skeleton__icon--${size}"></span>`;
}

function repeatHtml(count: number, renderItem: () => string): string {
  return Array.from({ length: count }, renderItem).join('');
}
