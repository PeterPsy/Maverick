import { ProviderStatus, SecretGrant, SecretGrantTarget, SecretRecord } from './api';
import { grantStatus, grantUsesSecret } from './vaultUtils';

export type ReadinessIssue = {
  id: string;
  severity: 'blocked' | 'warning';
  title: string;
  detail: string;
  status: string;
  action?: string;
};

type ConsumerTargets = {
  backend: string[];
  cli: string[];
  mcp: string[];
  all: string[];
};

export function computeReadinessIssues({
  grants,
  providerStatus,
  secrets,
  targets
}: {
  grants: SecretGrant[];
  providerStatus: ProviderStatus | null;
  secrets: SecretRecord[];
  targets: SecretGrantTarget[];
}): ReadinessIssue[] {
  const issues: ReadinessIssue[] = [];
  const knownTargetKeys = new Set<string>();

  for (const target of targets) {
    for (const logicalName of target.logical_names) {
      const consumerTargets = secretConsumerTargets(target, logicalName);
      for (const consumerTarget of consumerTargets.all) {
        knownTargetKeys.add(`${target.app_id}:${logicalName.toLowerCase()}:${consumerTarget}`);
      }
      for (const consumerTarget of consumerTargets.all) {
        if (!grants.some((grant) => isCurrentActiveGrant(grant) && grantCoversSecretTarget(grant, target.app_id, logicalName, consumerTarget))) {
          issues.push({
            id: `missing:${target.app_id}:${logicalName}:${consumerTarget}`,
            severity: 'blocked',
            title: `${target.name || target.app_id} needs ${logicalName}`,
            detail: `App ${target.app_id} has no current active grant for ${consumerLabel(consumerTarget)}.`,
            status: 'missing',
            action: 'Create grant'
          });
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
        title: `${grant.app_id}.${grant.logical_name} grant is ${status}`,
        detail: grant.reason || `Grant ${grant.grant_id} cannot currently deliver this secret.`,
        status
      });
    }
    if (grant.linked_secret_status && grant.linked_secret_status !== 'active') {
      issues.push({
        id: `secret-status:${grant.grant_id}`,
        severity: 'blocked',
        title: `${grant.app_id}.${grant.logical_name} points to a ${grant.linked_secret_status} secret`,
        detail: `Grant ${grant.grant_id} references ${grant.secret_ref}.`,
        status: grant.linked_secret_status
      });
    }
    if (grant.status === 'active' && !grantMatchesKnownConsumer(grant, knownTargetKeys)) {
      issues.push({
        id: `orphan-target:${grant.grant_id}`,
        severity: 'blocked',
        title: `${grant.app_id}.${grant.logical_name} has no enabled declaring consumer`,
        detail: `The app target is not currently returned by the grant target inventory.`,
        status: 'orphaned'
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
        detail: `${linkedActiveGrants.length} current grant(s) still reference this ${secret.status} secret.`,
        status: secret.status
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
      detail: providerStatus.blocked_detail || providerStatus.blocked_reason,
      status: needsCredential ? 'needs-credential' : providerStatus.blocked_reason
    });
  }

  return issues;
}

export function secretConsumerTargets(target: SecretGrantTarget, logicalName: string): ConsumerTargets {
  const normalized = logicalName.toLowerCase();
  const consumer = target.consumers?.[normalized];
  const backend = consumer?.backend || (!target.consumers && target.surfaces?.backend) ? [appSecretTarget('backend')] : [];
  const cli = (consumer?.cli_commands || (!target.consumers ? target.surfaces?.cli_commands : []) || []).map((command) => appSecretTarget(`cli/${command}`));
  const mcp = (consumer?.mcp_tools || (!target.consumers ? target.surfaces?.mcp_tools : []) || []).map((tool) => appSecretTarget(`mcp/${tool}`));
  return { backend, cli, mcp, all: [...backend, ...cli, ...mcp] };
}

export function grantCoversSecretTarget(grant: SecretGrant, appId: string, logicalName: string, target: string): boolean {
  if (grant.app_id !== appId || grant.logical_name.toLowerCase() !== logicalName.toLowerCase()) {
    return false;
  }
  if (!grant.actions.map((action) => action.toLowerCase()).includes('app.backend')) {
    return false;
  }
  return grant.target_patterns.some((pattern) => patternAllowsTarget(pattern, target));
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
    if (grantCoversSecretTarget(grant, appId, logicalName, target)) {
      return true;
    }
  }
  return false;
}

export function appSecretTarget(surface: string): string {
  const normalized = surface.trim().toLowerCase().replace(/_/g, '-') || 'entrypoint';
  return `maverick://app.backend/${normalized}`;
}

function patternAllowsTarget(pattern: string, target: string): boolean {
  if (pattern === '*') {
    return true;
  }
  const escaped = pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*');
  return new RegExp(`^${escaped}$`).test(target);
}

function consumerLabel(target: string): string {
  return target.replace('maverick://app.backend/', '').replace(/^cli\//, 'CLI ').replace(/^mcp\//, 'MCP ');
}
