import type { AgenticAdminItem } from './adminApi';

export type AgenticProfileRevisionGroup = {
  primary: AgenticAdminItem;
  otherRevisions: AgenticAdminItem[];
  otherEnabledCount: number;
};

/** Presentation only: retain exact server items and every binding/revision. */
export function groupAgenticProfileRevisions(items: readonly AgenticAdminItem[]): AgenticProfileRevisionGroup[] {
  const groups = new Map<string, AgenticAdminItem[]>();
  for (const item of items) {
    const family = item.execution_family || (item.runtime_engine_id === 'codex' ? 'native_agent' : null);
    const key = JSON.stringify([family, item.runtime_engine_id, item.model_provider_id, item.definition_id]);
    const group = groups.get(key) || [];
    group.push(item);
    groups.set(key, group);
  }
  return Array.from(groups.values(), (revisions) => {
    const ordered = revisions.slice().sort((left, right) =>
      bindingPriority(right) - bindingPriority(left)
        || compareRevisions(right.definition_revision, left.definition_revision)
    );
    const [primary, ...otherRevisions] = ordered;
    return {
      primary,
      otherRevisions,
      otherEnabledCount: otherRevisions.filter((item) => item.binding?.enabled).length,
    };
  });
}

function bindingPriority(item: AgenticAdminItem): number {
  return item.binding?.enabled ? (item.binding.is_default ? 2 : 1) : 0;
}

/** Natural presentation order, not evidence of publication recency for labels. */
function compareRevisions(left: string, right: string): number {
  const leftParts = left.match(/[0-9]+|[^0-9]+/g) || [];
  const rightParts = right.match(/[0-9]+|[^0-9]+/g) || [];
  for (let index = 0; index < Math.min(leftParts.length, rightParts.length); index++) {
    const a = leftParts[index];
    const b = rightParts[index];
    // Neither Number() nor ICU numeric collation covers arbitrary-length runs.
    // Compare significant decimal digits by length, then exact code-unit order.
    if (/^[0-9]+$/.test(a) && /^[0-9]+$/.test(b)) {
      const digitsA = a.replace(/^0+/, '') || '0';
      const digitsB = b.replace(/^0+/, '') || '0';
      const order = digitsA.length - digitsB.length || compareText(digitsA, digitsB);
      if (order) return order;
    } else {
      const order = compareText(a, b);
      if (order) return order;
    }
  }
  return leftParts.length - rightParts.length || compareText(left, right);
}

function compareText(left: string, right: string): number {
  return left === right ? 0 : left < right ? -1 : 1;
}
