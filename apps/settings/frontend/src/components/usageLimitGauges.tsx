import React from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { Gauge } from '@/components/ui/gauge-1';

const mountedRoots = new Map<Element, Root>();
const maverickGaugeColors = {
  primary: 'var(--maverick-accent)',
  secondary: 'var(--maverick-border-strong)'
};

export function unmountUsageLimitGauges() {
  mountedRoots.forEach((root) => root.unmount());
  mountedRoots.clear();
}

export function mountUsageLimitGauges() {
  document.querySelectorAll<HTMLElement>('[data-provider-usage-gauge]').forEach((element) => {
    const rawValue = Number(element.dataset.providerUsageGauge || 0);
    const value = Math.round(Math.max(0, Math.min(100, Number.isFinite(rawValue) ? rawValue : 0)));
    const root = createRoot(element);
    root.render(
      <Gauge
        colors={maverickGaugeColors}
        indeterminate={element.dataset.providerUsageIndeterminate === 'true'}
        showValue
        size="medium"
        value={value}
      />
    );
    mountedRoots.set(element, root);
  });
}
