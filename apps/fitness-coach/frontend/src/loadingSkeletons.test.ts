import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const currentDir = dirname(fileURLToPath(import.meta.url));

function readSource(path: string) {
  return readFileSync(resolve(currentDir, path), 'utf8');
}

describe('initial loading skeletons', () => {
  it('renders app-owned skeletons while the first workout load is pending', () => {
    const appSource = readSource('App.tsx');
    const sidebarSource = readSource('widgets/fitness-coach-sidebar/main.tsx');

    expect(appSource).toContain('const [isInitialLoading, setIsInitialLoading] = useState(true);');
    expect(appSource).toContain('<FitnessMainSkeleton />');
    expect(appSource).toContain('role="status" aria-label="Fitness Coach is loading"');
    expect(sidebarSource).toContain('const [isInitialLoading, setIsInitialLoading] = useState(true);');
    expect(sidebarSource).toContain('<FitnessSidebarSkeleton />');
  });

  it('uses the Checklist-style shimmer treatment with Fitness Coach class ownership', () => {
    const appStyles = readSource('styles.css');
    const sidebarStyles = readSource('widgets/fitness-coach-sidebar/styles.css');

    expect(appStyles).toMatch(/\.fitness-loading-skeleton__line::after[\s\S]*linear-gradient\(90deg,\s*transparent,\s*rgba\(255,\s*255,\s*255,\s*0\.12\),\s*transparent\)/);
    expect(appStyles).toContain('animation: fitness-loading-skeleton-shimmer 1.45s ease-in-out infinite;');
    expect(sidebarStyles).toMatch(/\.fitness-sidebar-skeleton__icon::after[\s\S]*linear-gradient\(90deg,\s*transparent,\s*rgba\(255,\s*255,\s*255,\s*0\.12\),\s*transparent\)/);
    expect(sidebarStyles).toContain('animation: fitness-sidebar-skeleton-shimmer 1.45s ease-in-out infinite;');
  });
});
