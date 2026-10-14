import assert from 'node:assert/strict';
import { readFile, mkdtemp, mkdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { chromium, file, portrait, startPreviewFixture } from './storagePreviewFixture.mjs';

test('mounted portrait preview, fullscreen fallback, native fullscreen, focus and downloads', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'storage-preview-test-'));
  const fixture = await startPreviewFixture();
  const { downloads, shellOrigin } = fixture;
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    for (const scenario of [{ width: 1000, height: 900, native: false }, { width: 1000, height: 900, native: true },
      { width: 390, height: 844, native: false }, { width: 320, height: 568, native: false }]) {
      const page = await browser.newPage({ viewport: scenario, acceptDownloads: true });
      page.setDefaultTimeout(10_000);
      page.on('pageerror', (error) => console.error('Storage fixture error:', error.message));
      await page.goto(`${shellOrigin}/${scenario.width <= 780 ? 'mobile' : scenario.native ? 'native' : 'fallback'}`);
      const frame = page.frameLocator('iframe');
      const opener = frame.getByRole('button', { name: `Open ${file.name}`, exact: true });
      try { await opener.click(); }
      catch (error) {
        console.error('Storage fixture UI:', await page.frames()[1].locator('body').innerText());
        throw error;
      }
      const close = frame.getByRole('button', { name: 'Close preview', exact: true });
      await close.waitFor();
      const image = frame.getByRole('dialog').locator('.storage-image-preview > img');
      await image.waitFor();
      await image.evaluate((element) => element.decode());
      assert.equal(await close.evaluate((element) => document.activeElement === element), true);
      const initialClose = await close.boundingBox();
      assert.ok(initialClose.x >= 0 && initialClose.x + initialClose.width <= scenario.width, 'normal preview controls stay within the viewport');
      if (scenario.width > 780) {
        await frame.getByRole('button', { name: 'Open preview full screen', exact: true }).click();
        await frame.getByRole('button', { name: 'Exit full screen', exact: true }).waitFor();
        await page.waitForTimeout(100);
      }
      const layout = await frame.getByRole('dialog').evaluate((dialog) => {
        const rect = (selector) => dialog.querySelector(selector).getBoundingClientRect().toJSON();
        return { image: rect('.storage-image-preview > img'), body: rect('.preview-modal-body'),
          close: rect('[aria-label="Close preview"]'), viewport: { width: innerWidth, height: innerHeight } };
      });
      assert.ok(layout.image.height <= layout.body.height + 1, 'portrait image stays inside the available height');
      assert.ok(layout.close.top >= 0 && layout.close.bottom <= layout.viewport.height, 'Close stays visible vertically');
      if (scenario.width <= 780) assert.ok(layout.close.top >= 60, 'preview clears the mobile shell header');
      assert.ok(layout.close.right <= layout.viewport.width, 'Close stays visible on narrow screens');
      if (process.env.STORAGE_PREVIEW_SCREENSHOT_DIR) {
        await mkdir(process.env.STORAGE_PREVIEW_SCREENSHOT_DIR, { recursive: true });
        await page.screenshot({ path: join(process.env.STORAGE_PREVIEW_SCREENSHOT_DIR, `preview-${scenario.width}-${scenario.native}.png`) });
      }
      const download = frame.getByRole('button', { name: 'Download file', exact: true });
      const downloadEvent = page.waitForEvent('download');
      await download.click();
      const saved = await downloadEvent;
      assert.equal(saved.suggestedFilename(), file.name);
      const target = join(directory, `${scenario.width}-${scenario.native}.png`);
      await saved.saveAs(target);
      assert.equal(await readFile(target, 'utf8'), portrait);
      await close.click();
      await frame.getByRole('dialog').waitFor({ state: 'detached' });
      assert.equal(await opener.evaluate((element) => document.activeElement === element), true);
      await opener.click();
      await close.waitFor();
      if (scenario.width > 780) {
        await frame.getByRole('button', { name: 'Open preview full screen', exact: true }).click();
        await frame.getByRole('button', { name: 'Exit full screen', exact: true }).waitFor();
        await close.press('Escape');
        await frame.getByRole('button', { name: 'Open preview full screen', exact: true }).waitFor();
      }
      await close.press('Escape');
      await frame.getByRole('dialog').waitFor({ state: 'detached' });
      await page.close();
    }
    assert.equal(downloads.length, 4);
  } finally {
    await browser?.close();
    await fixture.close();
    await rm(directory, { recursive: true, force: true });
  }
});
