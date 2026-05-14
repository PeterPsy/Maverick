import type { MigrationPlan, MigrationResult } from './adminApi';
import { escapeAttr, escapeHtml } from './html';
import { pageSettingsBlockHtml } from './pageFrame';
import type { SettingsPage } from './pages';
import type { MigrationProgress, PersistenceMigrationViewState } from './persistenceController';

export function persistencePageHtml(page: SettingsPage, state: PersistenceMigrationViewState) {
  return `${pageSettingsBlockHtml(page)}
    ${persistenceHtml(state)}`;
}

export function persistenceMigrationModalHtml(state: PersistenceMigrationViewState) {
  const { deleteSourceAfterMigration, migrationPlan, migrationProgress, migrationTarget, persistence } = state;
  if (!migrationTarget || !persistence) return '';
  const source = persistence.active_adapter.kind.toUpperCase();
  const target = migrationTarget.toUpperCase();
  const isBusy = Boolean(migrationProgress && !['complete', 'failed'].includes(migrationProgress.phase));
  const canApply = Boolean(migrationPlan && !migrationPlan.same_adapter && !isBusy);
  return `<div class="settings-modal-backdrop" role="presentation">
    <section class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="adapter-migration-title">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Confirm migration</p>
          <h2 id="adapter-migration-title">${source} → ${target}</h2>
        </div>
        <button type="button" class="settings-icon-button" id="close-migration-modal" aria-label="Close" ${isBusy ? 'disabled' : ''}>
          <span class="material-symbols-rounded" aria-hidden="true">close</span>
        </button>
      </div>
      ${migrationPlan ? migrationPlanHtml(migrationPlan) : pendingPlanHtml(migrationProgress)}
      ${targetDraftFormHtml(state)}
      <label class="settings-toggle settings-migration-delete-source">
        <input id="settings-delete-source" type="checkbox" ${deleteSourceAfterMigration ? 'checked' : ''} ${isBusy ? 'disabled' : ''} />
        Schedule source cleanup after restart health check
      </label>
      <p class="settings-card-copy">Leave cleanup off to preserve the current source adapter data as a rollback point. Cleanup is a separate explicit choice and requires backend restart.</p>
      <div class="settings-modal-actions">
        <button type="button" class="settings-secondary" id="cancel-migration" ${isBusy ? 'disabled' : ''}>Cancel</button>
        <button type="button" class="settings-secondary" id="validate-migration" ${isBusy ? 'disabled' : ''}>
          <span class="material-symbols-rounded" aria-hidden="true">rule</span>
          Validate dry run
        </button>
        <button type="button" class="${deleteSourceAfterMigration ? 'settings-danger' : 'settings-secondary'}" id="confirm-migration" ${canApply ? '' : 'disabled'}>
          <span class="material-symbols-rounded" aria-hidden="true">sync_alt</span>
          ${deleteSourceAfterMigration ? 'Apply and schedule cleanup' : 'Apply migration'}
        </button>
      </div>
    </section>
  </div>`;
}

function targetDraftFormHtml(state: PersistenceMigrationViewState) {
  const draft = state.targetDraft;
  if (!draft) return '';
  const isBusy = Boolean(state.migrationProgress && !['complete', 'failed'].includes(state.migrationProgress.phase));
  return `<div class="settings-migration-target">
    <label class="settings-platform-field">
      <span>JSON root</span>
      <input data-migration-field="json_root" value="${escapeAttr(draft.json_root)}" ${isBusy ? 'disabled' : ''} />
    </label>
    ${
      draft.kind === 'mongo'
        ? `<label class="settings-platform-field">
          <span>Mongo URI</span>
          <input data-migration-field="mongodb_uri" value="${escapeAttr(draft.mongodb_uri)}" ${isBusy ? 'disabled' : ''} />
        </label>
        <label class="settings-platform-field">
          <span>Mongo database</span>
          <input data-migration-field="mongodb_database" value="${escapeAttr(draft.mongodb_database)}" ${isBusy ? 'disabled' : ''} />
        </label>
        <label class="settings-platform-field">
          <span>Mongo username</span>
          <input data-migration-field="mongodb_username" value="${escapeAttr(draft.mongodb_username || '')}" ${isBusy ? 'disabled' : ''} />
        </label>
        <label class="settings-platform-field">
          <span>Password secret ref</span>
          <input data-migration-field="mongodb_password_ref" value="${escapeAttr(draft.mongodb_password_ref || '')}" ${isBusy ? 'disabled' : ''} />
        </label>`
        : ''
    }
  </div>`;
}

function persistenceHtml(state: PersistenceMigrationViewState) {
  const { migrationProgress, migrationResult, persistence } = state;
  if (!persistence) {
    return `<section class="settings-card settings-persistence">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Persistence</p>
          <h2>Control plane adapter</h2>
        </div>
        <span class="settings-pill settings-pill-muted">offline</span>
      </div>
      <p class="settings-card-copy">The core persistence surfaces are not available in the active backend.</p>
    </section>`;
  }
  const active = persistence.active_adapter;
  const totalDocuments = persistence.collections.reduce((total, item) => total + item.count, 0);
  const jsonActive = active.kind === 'json';
  const mongoActive = active.kind === 'mongo';
  const locked = migrationProgress && !['complete', 'failed'].includes(migrationProgress.phase);
  return `<section class="settings-card settings-persistence">
    <div class="settings-heading">
      <div>
        <p class="settings-kicker">Persistence</p>
        <h2>Control plane adapter</h2>
      </div>
      <span class="settings-pill">${totalDocuments} documents</span>
    </div>
    <div class="settings-adapter-cards">
      <button type="button" class="settings-adapter-card ${jsonActive ? 'is-active' : ''}" ${jsonActive || locked ? 'disabled' : 'data-adapter-target="json"'}>
        <span class="settings-adapter-card-icon material-symbols-rounded" aria-hidden="true">${jsonActive ? 'check_circle' : 'database'}</span>
        <span>
          <strong>JSON</strong>
          <small>${escapeHtml(jsonActive ? active.json_root : 'data/control-plane/json')}</small>
        </span>
        <em>${jsonActive ? 'Current' : 'Review migration'}</em>
      </button>
      <button type="button" class="settings-adapter-card ${mongoActive ? 'is-active' : ''}" ${mongoActive || locked ? 'disabled' : 'data-adapter-target="mongo"'}>
        <span class="settings-adapter-card-icon material-symbols-rounded" aria-hidden="true">${mongoActive ? 'check_circle' : 'database'}</span>
        <span>
          <strong>Mongo</strong>
          <small>${escapeHtml(mongoActive ? active.mongo_database : 'mongodb://127.0.0.1:27017/maverick')}</small>
        </span>
        <em>${mongoActive ? 'Current' : 'Review migration'}</em>
      </button>
    </div>
    ${migrationProgressHtml(migrationProgress)}
    ${migrationResultHtml(migrationResult)}
  </section>`;
}

function migrationProgressHtml(progress: MigrationProgress | null) {
  if (!progress) return '';
  return `<div class="settings-migration-progress ${progress.phase === 'failed' ? 'is-failed' : ''} ${progress.phase === 'complete' ? 'is-complete' : ''}">
    <div class="settings-migration-progress-heading">
      <span class="material-symbols-rounded" aria-hidden="true">${progress.phase === 'complete' ? 'check_circle' : progress.phase === 'failed' ? 'error' : 'sync'}</span>
      <span>
        <strong>${escapeHtml(progress.title)}</strong>
        <small>${escapeHtml(progress.detail)}</small>
      </span>
      <em>${progress.percent}%</em>
    </div>
    <div class="settings-progress-track" aria-label="Migration progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${progress.percent}">
      <span style="width: ${progress.percent}%"></span>
    </div>
  </div>`;
}

function migrationResultHtml(result: MigrationResult | null) {
  if (!result) return '';
  const copied = result.collections.reduce((total, item) => total + item.count, 0);
  return `<div class="settings-migration-result">
    <span class="material-symbols-rounded" aria-hidden="true">task_alt</span>
    <span>
      <strong>Last migration</strong>
      <small>${copied} documents · target ${escapeHtml(result.target_adapter.kind)} · cleanup ${result.source_cleanup?.scheduled ? 'scheduled' : 'not requested'}</small>
    </span>
  </div>`;
}

function pendingPlanHtml(progress: MigrationProgress | null) {
  return `<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">rule</span>
    <span>
      <strong>${escapeHtml(progress?.title || 'Dry run not validated')}</strong>
      <small>${escapeHtml(progress?.detail || 'Adjust the target fields, then validate the dry run before applying migration.')}</small>
    </span>
  </div>`;
}

function migrationPlanHtml(plan: MigrationPlan) {
  const sourceTotal = plan.collections.reduce((total, item) => total + item.count, 0);
  const targetTotal = plan.target_collections.reduce((total, item) => total + item.count, 0);
  return `<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">${plan.same_adapter ? 'block' : 'rule'}</span>
    <span>
      <strong>${plan.same_adapter ? 'Target already active' : 'Dry run complete'}</strong>
      <small>${sourceTotal} source documents · ${targetTotal} target documents before copy · env ${escapeHtml(plan.env_file)}</small>
    </span>
    <div class="settings-migration-collections">
      ${plan.collections.map((item) => `<span><strong>${escapeHtml(item.name)}</strong><small>${item.count}</small></span>`).join('')}
    </div>
  </div>`;
}
