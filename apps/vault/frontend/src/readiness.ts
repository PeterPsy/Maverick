import { ProviderStatus, SecretGrant, SecretGrantNeed, SecretGrantTarget, SecretRecord } from './api';
import { grantStatus, grantUsesSecret } from './vaultUtils';

export type ConnectionIssue = {
  id: string;
  severity: 'blocked' | 'warning';
  title: string;
  summary: string;
  status: string;
  appId: string | null;
  appDisplayName: string;
  credentialLabel: string;
  userInputNeeded: boolean;
  recommendedAction: string;
  technicalDetails: string;
  credentialSecretIds: string[];
};

export type ReadinessIssue = ConnectionIssue;

type ConsumerTargets = {
  backend: string[];
  cli: string[];
  mcp: string[];
  all: string[];
};

export function computeReadinessIssues({
  grants,
  grantNeeds = [],
  providerStatus,
  secrets,
  targets
}: {
  grants: SecretGrant[];
  grantNeeds?: SecretGrantNeed[];
  providerStatus: ProviderStatus | null;
  secrets: SecretRecord[];
  targets: SecretGrantTarget[];
}): ConnectionIssue[] {
  const issues: ConnectionIssue[] = [];
  const knownTargetKeys = new Set<string>();

  if (grantNeeds.length) {
    for (const need of grantNeeds) {
      const issue = issueFromCoreNeed(need);
      if (issue) {
        issues.push(issue);
      }
      for (const target of need.recommended_grant?.target_patterns || []) {
        knownTargetKeys.add(`${need.app_id}:${need.logical_name.toLowerCase()}:${target}`);
      }
    }
  } else {
    for (const target of targets) {
      for (const logicalName of target.logical_names) {
        const consumerTargets = secretConsumerTargets(target, logicalName);
        for (const consumerTarget of consumerTargets.all) {
          knownTargetKeys.add(`${target.app_id}:${logicalName.toLowerCase()}:${consumerTarget}`);
        }
        if (target.consumers?.[logicalName.toLowerCase()]?.resource_scoped) {
          continue;
        }
        for (const consumerTarget of consumerTargets.all) {
          if (!grants.some((grant) => isCurrentActiveGrant(grant) && grantCoversSecretTarget(grant, target.app_id, logicalName, consumerTarget))) {
            const credentialLabel = humanizeNeedLabel(logicalName);
            const candidateIds = matchingSecretIds(secrets, logicalName);
            issues.push({
              id: `missing:${target.app_id}:${logicalName}:${consumerTarget}`,
              severity: candidateIds.length ? 'warning' : 'blocked',
              title: `${target.name || humanizeNeedLabel(target.app_id)} needs ${credentialLabel}`,
              summary: candidateIds.length
                ? 'A matching saved credential exists, but this app is not connected to it yet.'
                : 'Add this credential value before the app can use it.',
              status: candidateIds.length ? 'needs-access' : 'needs-value',
              appId: target.app_id,
              appDisplayName: target.name || humanizeNeedLabel(target.app_id),
              credentialLabel,
              userInputNeeded: !candidateIds.length,
              recommendedAction: candidateIds.length ? 'Review and connect credential' : 'Add credential value',
              technicalDetails: `Missing active grant for ${target.app_id} on ${consumerLabel(consumerTarget)}.`,
              credentialSecretIds: candidateIds
            });
          }
        }
      }
    }
  }

  for (const grant of grants) {
    const status = grantStatus(grant);
    if (status !== 'active') {
      issues.push({
        id: `grant-status:${grant.grant_id}`,
        severity: status === 'revoked' ? 'warning' : 'blocked',
        title: `${appNameForGrant(grant, targets)} credential access is ${status}`,
        summary: 'A saved credential exists, but the app connection cannot use it right now.',
        status,
        appId: grant.app_id,
        appDisplayName: appNameForGrant(grant, targets),
        credentialLabel: humanizeNeedLabel(grant.logical_name),
        userInputNeeded: false,
        recommendedAction: 'Review credential connection',
        technicalDetails: grant.reason || `Grant ${grant.grant_id} cannot currently deliver this credential.`,
        credentialSecretIds: secretIdsForGrant(grant, secrets)
      });
    }
    if (grant.linked_secret_status && grant.linked_secret_status !== 'active') {
      issues.push({
        id: `secret-status:${grant.grant_id}`,
        severity: 'blocked',
        title: `${appNameForGrant(grant, targets)} points to a ${grant.linked_secret_status} credential`,
        summary: 'Replace or rotate the saved value before this app can use it.',
        status: grant.linked_secret_status,
        appId: grant.app_id,
        appDisplayName: appNameForGrant(grant, targets),
        credentialLabel: humanizeNeedLabel(grant.logical_name),
        userInputNeeded: true,
        recommendedAction: 'Rotate or replace credential',
        technicalDetails: `Grant ${grant.grant_id} references ${grant.secret_ref}.`,
        credentialSecretIds: secretIdsForGrant(grant, secrets)
      });
    }
    if (grant.status === 'active' && !grantMatchesKnownConsumer(grant, knownTargetKeys)) {
      issues.push({
        id: `orphan-target:${grant.grant_id}`,
        severity: 'blocked',
        title: `${appNameForGrant(grant, targets)} has a stale credential connection`,
        summary: 'The app no longer declares this credential path.',
        status: 'orphaned',
        appId: grant.app_id,
        appDisplayName: appNameForGrant(grant, targets),
        credentialLabel: humanizeNeedLabel(grant.logical_name),
        userInputNeeded: false,
        recommendedAction: 'Review advanced connection details',
        technicalDetails: 'The target is not currently returned by the grant target inventory.',
        credentialSecretIds: secretIdsForGrant(grant, secrets)
      });
    }
  }

  for (const secret of secrets) {
    if (secret.status === 'active') {
      continue;
    }
    const linkedActiveGrants = grants.filter((grant) => isCurrentActiveGrant(grant) && grantUsesSecret(grant, secret));
    if (linkedActiveGrants.length) {
      issues.push({
        id: `disabled-secret:${secret.secret_id}`,
        severity: 'blocked',
        title: `${secret.label} is linked to active grants`,
        summary: `${linkedActiveGrants.length} app connection(s) still reference this ${secret.status} credential.`,
        status: secret.status,
        appId: null,
        appDisplayName: linkedActiveGrants.map((grant) => appNameForGrant(grant, targets)).join(', ') || 'Workspace',
        credentialLabel: secret.label,
        userInputNeeded: true,
        recommendedAction: 'Rotate or replace credential',
        technicalDetails: `${linkedActiveGrants.length} active grant(s) still reference ${secret.secret_id}.`,
        credentialSecretIds: [secret.secret_id]
      });
    }
  }

  if (providerStatus?.blocked_reason) {
    const activeProvider = providerStatus.active_provider;
    const needsCredential = Boolean(activeProvider?.requires_credentials) || /credential|binding/i.test(providerStatus.blocked_detail || providerStatus.blocked_reason);
    issues.push({
      id: 'provider-status',
      severity: needsCredential ? 'blocked' : 'warning',
      title: activeProvider ? `${activeProvider.label} provider is not ready` : 'Runtime provider is not ready',
      summary: providerStatus.blocked_detail || providerStatus.blocked_reason,
      status: needsCredential ? 'needs-credential' : providerStatus.blocked_reason,
      appId: null,
      appDisplayName: activeProvider?.label || 'Runtime provider',
      credentialLabel: 'Provider credential',
      userInputNeeded: needsCredential,
      recommendedAction: needsCredential ? 'Add provider credential' : 'Review provider status',
      technicalDetails: providerStatus.blocked_detail || providerStatus.blocked_reason,
      credentialSecretIds: []
    });
  }

  return issues;
}

function issueFromCoreNeed(need: SecretGrantNeed): ConnectionIssue | null {
  const action = need.user_action || 'review';
  if (action === 'none') {
    return null;
  }
  const credentialLabel = need.human_label || humanizeNeedLabel(need.logical_name);
  const appDisplayName = need.app_name || humanizeNeedLabel(need.app_id);
  const candidateIds = (need.credential_match?.candidates || [])
    .map((candidate) => candidate.secret_id)
    .filter((secretId): secretId is string => Boolean(secretId));
  return {
    id: `need:${need.app_id}:${need.logical_name}:${need.scope?.label || 'workspace'}`,
    severity: severityForNeed(need),
    title: titleForNeed(appDisplayName, credentialLabel, action),
    summary: summaryForNeed(action, need),
    status: statusForNeed(action, need),
    appId: need.app_id,
    appDisplayName,
    credentialLabel,
    userInputNeeded: userInputNeededForAction(action),
    recommendedAction: recommendedActionLabel(action),
    technicalDetails: [
      `Core value state: ${need.value_state}.`,
      `Core grant state: ${need.grant_state}.`,
      need.scope?.label ? `Scope: ${need.scope.label}.` : '',
      need.recommended_grant?.reason || ''
    ].filter(Boolean).join(' '),
    credentialSecretIds: candidateIds
  };
}

function severityForNeed(need: SecretGrantNeed): ConnectionIssue['severity'] {
  if (['add_value', 'rotate_or_replace_value', 'complete_app_setup', 'reconnect_app'].includes(need.user_action)) {
    return 'blocked';
  }
  if (need.value_state === 'missing_or_unmatched' || need.grant_state === 'orphaned') {
    return 'blocked';
  }
  return 'warning';
}

function titleForNeed(appDisplayName: string, credentialLabel: string, action: string): string {
  if (action === 'add_value') {
    return `Add ${credentialLabel} for ${appDisplayName}`;
  }
  if (action === 'create_grant') {
    return `Connect ${credentialLabel} to ${appDisplayName}`;
  }
  if (action === 'rotate_or_replace_value') {
    return `Refresh ${credentialLabel} for ${appDisplayName}`;
  }
  if (action === 'complete_app_setup') {
    return `Complete setup for ${appDisplayName}`;
  }
  if (action === 'reconnect_app') {
    return `Reconnect ${appDisplayName}`;
  }
  return `Review ${credentialLabel} for ${appDisplayName}`;
}

function summaryForNeed(action: string, need: SecretGrantNeed): string {
  if (action === 'add_value') {
    return 'The app declares a credential need, but no matching saved value is ready.';
  }
  if (action === 'create_grant') {
    return 'A matching credential is saved, but this app is not connected to it yet.';
  }
  if (action === 'review_value_match') {
    return 'Vault found a possible credential match that needs confirmation.';
  }
  if (action === 'rotate_or_replace_value') {
    return 'The saved value is not active and should be replaced.';
  }
  if (action === 'complete_app_setup') {
    return 'This app manages the credential value. Complete the app setup flow so it can store the value through Core Secrets.';
  }
  if (action === 'reconnect_app') {
    return 'This app manages the credential value, but the saved connection is not active. Reconnect the app.';
  }
  if (need.grant_state && need.grant_state !== 'active') {
    return 'The credential connection needs admin review.';
  }
  return 'This credential path needs review before the app can use it.';
}

function statusForNeed(action: string, need: SecretGrantNeed): string {
  if (action === 'add_value') {
    return 'needs-value';
  }
  if (action === 'create_grant') {
    return 'needs-access';
  }
  if (action === 'rotate_or_replace_value') {
    return 'needs-refresh';
  }
  if (action === 'complete_app_setup') {
    return 'needs-app-setup';
  }
  if (action === 'reconnect_app') {
    return 'needs-reconnect';
  }
  return need.grant_state || need.value_state || 'review';
}

function recommendedActionLabel(action: string): string {
  if (action === 'add_value') {
    return 'Add credential value';
  }
  if (action === 'create_grant') {
    return 'Review and connect credential';
  }
  if (action === 'review_value_match') {
    return 'Review matching credential';
  }
  if (action === 'rotate_or_replace_value') {
    return 'Rotate or replace credential';
  }
  if (action === 'complete_app_setup') {
    return 'Complete app setup';
  }
  if (action === 'reconnect_app') {
    return 'Reconnect app';
  }
  if (action === 'review_grant') {
    return 'Review credential connection';
  }
  return 'Review issue';
}

function userInputNeededForAction(action: string): boolean {
  return ['add_value', 'review_value_match', 'rotate_or_replace_value', 'complete_app_setup', 'reconnect_app'].includes(action);
}

export function secretConsumerTargets(target: SecretGrantTarget, logicalName: string): ConsumerTargets {
  const normalized = logicalName.toLowerCase();
  const consumer = target.consumers?.[normalized];
  const backend = consumer?.backend || (!target.consumers && target.surfaces?.backend) ? [appSecretTarget('backend')] : [];
  const cli = (consumer?.cli_commands || (!target.consumers ? target.surfaces?.cli_commands : []) || []).map((command) => appSecretTarget(`cli/${command}`));
  const mcp = (consumer?.mcp_tools || (!target.consumers ? target.surfaces?.mcp_tools : []) || []).map((tool) => appSecretTarget(`mcp/${tool}`));
  return { backend, cli, mcp, all: [...backend, ...cli, ...mcp] };
}

export function grantCoversSecretTarget(
  grant: SecretGrant,
  appId: string,
  logicalName: string,
  target: string,
  resourceType?: string | null,
  resourceId?: string | null
): boolean {
  if (grant.app_id !== appId || grant.logical_name.toLowerCase() !== logicalName.toLowerCase()) {
    return false;
  }
  if (!grant.actions.map((action) => action.toLowerCase()).includes('app.backend')) {
    return false;
  }
  if (!grantResourceMatches(grant, resourceType, resourceId)) {
    return false;
  }
  const targetVariants = targetVariantsForResourceScope(target, resourceType, resourceId);
  return grant.target_patterns.some((pattern) => targetVariants.some((candidate) => patternAllowsTarget(pattern, candidate)));
}

export function isCurrentActiveGrant(grant: SecretGrant) {
  if (grant.status !== 'active' || grantStatus(grant) !== 'active') {
    return false;
  }
  if (grant.linked_secret_status && grant.linked_secret_status !== 'active') {
    return false;
  }
  if (!grant.expires_at) {
    return true;
  }
  const expiresAt = Date.parse(grant.expires_at);
  return Number.isFinite(expiresAt) && expiresAt > Date.now();
}

function grantMatchesKnownConsumer(grant: SecretGrant, knownTargetKeys: Set<string>) {
  if (!isCurrentActiveGrant(grant)) {
    return true;
  }
  for (const key of knownTargetKeys) {
    const [appId, logicalName, ...targetParts] = key.split(':');
    const target = targetParts.join(':');
    if (grantMatchesConsumerTarget(grant, appId, logicalName, target)) {
      return true;
    }
  }
  return false;
}

export function appSecretTarget(surface: string): string {
  const normalized = surface.trim().toLowerCase().replace(/_/g, '-') || 'entrypoint';
  return `maverick://app.backend/${normalized}`;
}

function resourceScopedAppSecretTarget(target: string, resourceType?: string | null, resourceId?: string | null): string | null {
  const normalizedResourceType = normalizeTargetSegment(resourceType);
  const normalizedResourceId = normalizeTargetSegment(resourceId);
  if (!normalizedResourceType || !normalizedResourceId || !target.startsWith('maverick://app.backend/')) {
    return null;
  }
  return `${target}/${normalizedResourceType}/${normalizedResourceId}`;
}

function targetVariantsForResourceScope(target: string, resourceType?: string | null, resourceId?: string | null): string[] {
  const scopedTarget = resourceScopedAppSecretTarget(target, resourceType, resourceId);
  return scopedTarget ? [target, scopedTarget] : [target];
}

function patternAllowsTarget(pattern: string, target: string): boolean {
  if (pattern === '*') {
    return true;
  }
  const escaped = pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*');
  return new RegExp(`^${escaped}$`).test(target);
}

function grantResourceMatches(grant: SecretGrant, resourceType?: string | null, resourceId?: string | null): boolean {
  const grantResourceType = (grant.resource_type || '').trim().toLowerCase();
  const grantResourceId = (grant.resource_id || '').trim().toLowerCase();
  const requestedResourceType = (resourceType || '').trim().toLowerCase();
  const requestedResourceId = (resourceId || '').trim().toLowerCase();
  const grantScoped = Boolean(grantResourceType && grantResourceId);
  const requestScoped = Boolean(requestedResourceType && requestedResourceId);
  if (grantScoped !== requestScoped) {
    return false;
  }
  if (!grantScoped) {
    return true;
  }
  return grantResourceType === requestedResourceType && grantResourceId === requestedResourceId;
}

function grantMatchesConsumerTarget(grant: SecretGrant, appId: string, logicalName: string, target: string): boolean {
  if (grant.app_id !== appId || grant.logical_name.toLowerCase() !== logicalName.toLowerCase()) {
    return false;
  }
  if (!grant.actions.map((action) => action.toLowerCase()).includes('app.backend')) {
    return false;
  }
  const targetVariants = targetVariantsForResourceScope(target, grant.resource_type, grant.resource_id);
  return grant.target_patterns.some((pattern) => targetVariants.some((candidate) => patternAllowsTarget(pattern, candidate)));
}

function consumerLabel(target: string): string {
  return target.replace('maverick://app.backend/', '').replace(/^cli\//, 'CLI ').replace(/^mcp\//, 'MCP ');
}

function normalizeTargetSegment(value?: string | null): string {
  return (value || '').trim().toLowerCase().replace(/_/g, '-');
}

function humanizeNeedLabel(value: string): string {
  return value.replace(/[-_.]+/g, ' ').replace(/\s+/g, ' ').trim().replace(/\b\w/g, (char) => char.toUpperCase()) || 'Credential';
}

function matchingSecretIds(secrets: SecretRecord[], logicalName: string): string[] {
  const normalized = logicalName.trim().toLowerCase();
  const label = humanizeNeedLabel(logicalName).toLowerCase();
  return secrets
    .filter((secret) => secret.status === 'active' && ((secret.alias || '').toLowerCase() === normalized || secret.label.toLowerCase() === label))
    .map((secret) => secret.secret_id);
}

function appNameForGrant(grant: SecretGrant, targets: SecretGrantTarget[]): string {
  return targets.find((target) => target.app_id === grant.app_id)?.name || humanizeNeedLabel(grant.app_id);
}

function secretIdsForGrant(grant: SecretGrant, secrets: SecretRecord[]): string[] {
  const match = secrets.find((secret) => grantUsesSecret(grant, secret));
  return match ? [match.secret_id] : [];
}
