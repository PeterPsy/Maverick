import { expect, Page } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';

const root = resolve(process.cwd(), '../..');
export function backend(dataRoot: string, body: Record<string, unknown>, providers: Record<string, string> = {}) {
  const result = spawnSync('python3', ['apps/crm/tests/e2e/backend_fixture.py'], { cwd: root, input: JSON.stringify({ root: dataRoot, body, providers }), encoding: 'utf8', timeout: 25_000 });
  if (result.status !== 0) throw new Error(result.stderr || String(result.error));
  return JSON.parse(result.stdout) as { status: number; body: Record<string, any> };
}
export async function mount(page: Page, dataRoot: string, providers = { mail: 'test-mail' } as Record<string, string>) {
  backend(dataRoot, { action: 'crm.create_contact', id: 'contact_ada', display_name: 'Ada Example', email: 'ada@example.test' });
  backend(dataRoot, { action: 'crm.create_task', title: 'Prepare next conversation', due_at: '2026-01-01', contact_id: 'contact_ada' });
  await page.route('**/api/apps/crm/backend', async (route) => {
    const result = backend(dataRoot, route.request().postDataJSON(), providers);
    await route.fulfill({ status: result.status, contentType: 'application/json', body: JSON.stringify(result.body) });
  });
  await page.goto('/apps/crm/');
  await expect(page.getByRole('heading', { name: 'CRM records' })).toBeVisible();
}
