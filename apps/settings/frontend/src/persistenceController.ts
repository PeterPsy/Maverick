import {
  applyPersistenceMigration as applyPersistenceMigrationRequest,
  dryRunPersistenceMigration,
  type MigrationPlan,
  type MigrationResult,
  type MigrationTargetPayload,
  type PersistenceStatus,
} from './adminApi';

export type MigrationProgress = {
  target: 'json' | 'mongo';
  phase: 'validating' | 'applying' | 'restarting' | 'polling' | 'complete' | 'failed';
  percent: number;
  title: string;
  detail: string;
};

export type MigrationTargetDraft = MigrationTargetPayload;

export type PersistenceMigrationViewState = {
  deleteSourceAfterMigration: boolean;
  migrationPlan: MigrationPlan | null;
  migrationProgress: MigrationProgress | null;
  migrationResult: MigrationResult | null;
  migrationTarget: 'json' | 'mongo' | null;
  persistence: PersistenceStatus | null;
  targetDraft: MigrationTargetDraft | null;
};

type Notice = { tone: 'info' | 'success' | 'error'; message: string } | null;

export function createPersistenceController(context: {
  getPersistence: () => PersistenceStatus | null;
  render: () => void;
  requestPersistenceStatusQuiet: () => Promise<PersistenceStatus | null>;
  setNotice: (notice: Notice) => void;
  setPersistence: (status: PersistenceStatus) => void;
}) {
  let migrationTarget: 'json' | 'mongo' | null = null;
  let targetDraft: MigrationTargetDraft | null = null;
  let validatedDraftSignature = '';
  let migrationPlan: MigrationPlan | null = null;
  let migrationResult: MigrationResult | null = null;
  let migrationProgress: MigrationProgress | null = null;
  let deleteSourceAfterMigration = false;

  function viewState(): PersistenceMigrationViewState {
    return {
      deleteSourceAfterMigration,
      migrationPlan,
      migrationProgress,
      migrationResult,
      migrationTarget,
      persistence: context.getPersistence(),
      targetDraft,
    };
  }

  async function prepare(kind: 'json' | 'mongo') {
    const persistence = context.getPersistence();
    if (!persistence || persistence.active_adapter.kind === kind) {
      cancel();
      return;
    }
    migrationTarget = kind;
    targetDraft = defaultTargetDraft(kind, persistence);
    validatedDraftSignature = '';
    migrationPlan = null;
    deleteSourceAfterMigration = false;
    migrationProgress = null;
    context.setNotice(null);
    context.render();
  }

  function updateDraft(field: keyof MigrationTargetDraft, value: string, options: { render?: boolean } = {}) {
    if (!targetDraft) {
      return;
    }
    targetDraft = { ...targetDraft, [field]: value };
    migrationPlan = null;
    validatedDraftSignature = '';
    migrationProgress = null;
    if (options.render !== false) {
      context.render();
    }
  }

  function setDeleteSource(value: boolean) {
    deleteSourceAfterMigration = value;
    context.render();
  }

  function cancel() {
    migrationTarget = null;
    targetDraft = null;
    migrationPlan = null;
    validatedDraftSignature = '';
    migrationProgress = null;
    context.render();
  }

  async function validateDraft() {
    if (!targetDraft || !migrationTarget) {
      return;
    }
    migrationProgress = {
      target: migrationTarget,
      phase: 'validating',
      percent: 10,
      title: `Dry run to ${migrationTarget.toUpperCase()}`,
      detail: 'Validating target adapter and collection copy plan before applying changes.',
    };
    context.setNotice(null);
    context.render();
    try {
      const payload = normalizedTargetPayload(targetDraft);
      migrationPlan = await dryRunPersistenceMigration(payload);
      validatedDraftSignature = draftSignature(payload);
    } catch (error) {
      migrationProgress = null;
      migrationPlan = null;
      validatedDraftSignature = '';
      throw error;
    }
    migrationProgress = null;
    if (migrationPlan.same_adapter) {
      context.setNotice({ tone: 'info', message: 'The selected persistence adapter is already active.' });
    }
    context.render();
  }

  async function apply() {
    if (!targetDraft || !migrationTarget) {
      return;
    }
    const payload = normalizedTargetPayload(targetDraft);
    const currentSignature = draftSignature(payload);
    if (!migrationPlan || validatedDraftSignature !== currentSignature) {
      await validateDraft();
      return;
    }
    if (migrationPlan.same_adapter) {
      return;
    }
    migrationProgress = {
      target: migrationTarget,
      phase: 'applying',
      percent: 38,
      title: `Migration to ${migrationTarget.toUpperCase()}`,
      detail: 'Copying the validated control-plane plan to the target adapter.',
    };
    context.setNotice(null);
    context.render();
    try {
      migrationResult = await applyPersistenceMigrationRequest({
        ...payload,
        delete_source: deleteSourceAfterMigration,
        restart_backend: true,
      });
    } catch (error) {
      migrationProgress = {
        target: migrationTarget,
        phase: 'failed',
        percent: 100,
        title: 'Migration failed',
        detail: error instanceof Error ? error.message : 'Unable to apply migration.',
      };
      throw error;
    }
    const target = migrationTarget;
    migrationTarget = null;
    targetDraft = null;
    migrationPlan = null;
    validatedDraftSignature = '';
    migrationProgress = {
      target,
      phase: 'restarting',
      percent: 68,
      title: 'Restart backend',
      detail: migrationResult.backend_restart?.detail || 'Backend restart scheduled.',
    };
    context.render();
    await waitForCutover(target);
  }

  async function waitForCutover(kind: 'json' | 'mongo') {
    const startedAt = Date.now();
    const timeoutMs = 90_000;
    while (Date.now() - startedAt < timeoutMs) {
      migrationProgress = {
        target: kind,
        phase: 'polling',
        percent: 84,
        title: 'Verifying cutover',
        detail: 'Waiting for the backend to become healthy with the new adapter.',
      };
      context.render();
      const status = await context.requestPersistenceStatusQuiet();
      if (status?.active_adapter.kind === kind) {
        context.setPersistence(status);
        const cleanupScheduled = migrationResult?.source_cleanup?.scheduled === true;
        migrationProgress = {
          target: kind,
          phase: 'complete',
          percent: 100,
          title: 'Migration complete',
          detail: cleanupScheduled
            ? `Active adapter: ${kind.toUpperCase()}. Source cleanup is scheduled after health check.`
            : `Active adapter: ${kind.toUpperCase()}. Source storage was preserved.`,
        };
        context.setNotice({ tone: 'success', message: `Migration to ${kind.toUpperCase()} complete.` });
        context.render();
        return;
      }
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
    }
    migrationProgress = {
      target: kind,
      phase: 'failed',
      percent: 100,
      title: 'Verification not completed',
      detail: 'The backend did not confirm the new adapter before the timeout. Check service health and logs.',
    };
    context.setNotice({ tone: 'error', message: 'Migration not confirmed before the timeout.' });
    context.render();
  }

  return {
    apply,
    cancel,
    prepare,
    setDeleteSource,
    updateDraft,
    validateDraft,
    viewState,
  };
}

function defaultTargetDraft(kind: 'json' | 'mongo', persistence: PersistenceStatus): MigrationTargetDraft {
  const active = persistence.active_adapter;
  return {
    kind,
    json_root: active.json_root || 'data/control-plane/json',
    mongodb_uri: active.mongo_uri || 'mongodb://127.0.0.1:27017/maverick',
    mongodb_database: active.mongo_database || 'maverick',
    mongodb_username: active.mongo_username || '',
    mongodb_password_ref: active.mongo_password_ref || '',
  };
}

function normalizedTargetPayload(draft: MigrationTargetDraft): MigrationTargetPayload {
  return {
    kind: draft.kind,
    json_root: draft.json_root.trim() || 'data/control-plane/json',
    mongodb_uri: draft.mongodb_uri.trim(),
    mongodb_database: draft.mongodb_database.trim() || 'maverick',
    mongodb_username: draft.mongodb_username?.trim() || undefined,
    mongodb_password_ref: draft.mongodb_password_ref?.trim() || undefined,
  };
}

function draftSignature(draft: MigrationTargetPayload) {
  return JSON.stringify(normalizedTargetPayload(draft));
}
