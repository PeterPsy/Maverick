import assert from 'node:assert/strict';
import { test } from 'node:test';
import { chromium, fixtures, startPreviewFixture } from './storagePreviewFixture.mjs';

test('mobile app and Chat widgets contain and download images, PDF and long text', async () => {
  const fixture = await startPreviewFixture();
  const browser = await chromium.launch({ headless: true });
  try {
    for (const viewport of [{ width: 390, height: 844 }, { width: 320, height: 568 }, { width: 844, height: 390 }]) {
      const page = await browser.newPage({ viewport, isMobile: true, hasTouch: true, deviceScaleFactor: 3, acceptDownloads: true });
      page.setDefaultTimeout(15_000);
      for (const widget of [false, true]) {
        for (const item of fixtures) {
          await page.goto(`${fixture.shellOrigin}/mobile${widget ? `?widget=${item.file.id}` : ''}`);
          const frame = page.frameLocator('iframe');
          if (!widget) await frame.getByRole('button', { name: `Open ${item.file.name}`, exact: true }).click();
          const surface = frame.locator(widget ? '.file-widget__document' : '.preview-modal-content');
          await surface.waitFor();
          let image;
          if (item.file.preview_kind === 'image') {
            image = surface.getByRole('img', { name: item.file.name, exact: true });
            await image.waitFor();
            await image.evaluate((element) => element.decode());
          } else if (item.file.preview_kind === 'pdf') {
            const canvas = surface.getByRole('img', { name: 'PDF page 1', exact: true });
            await canvas.waitFor();
            const metrics = await canvas.evaluate((element) => ({
              width: element.getBoundingClientRect().width,
              viewport: element.closest('.pdf-preview__viewport').clientWidth,
              height: element.getBoundingClientRect().height,
              viewportHeight: element.closest('.pdf-preview__viewport').clientHeight,
            }));
            assert.ok(metrics.width <= metrics.viewport, 'PDF starts fitted to the actual width');
            assert.ok(metrics.height <= metrics.viewportHeight, 'the whole PDF page starts within the available height');
            assert.equal(await surface.getByRole('spinbutton', { name: 'PDF page' }).evaluate((input) => getComputedStyle(input).fontSize), '16px');
            await surface.getByRole('button', { name: 'Next page' }).click();
            await surface.getByRole('img', { name: 'PDF page 2', exact: true }).waitFor();
          } else {
            await surface.locator('pre').waitFor();
            const scrolling = widget ? surface : surface.locator('pre');
            assert.ok(await scrolling.evaluate((element) => {
              element.scrollTop = 500; return element.scrollTop > 0 && element.scrollHeight > element.clientHeight;
            }), 'long files scroll within their content area');
          }
          const bounds = await surface.boundingBox();
          assert.ok(bounds.x >= -1 && bounds.x + bounds.width <= viewport.width + 1, 'preview width stays within the frame');
          assert.ok(bounds.y >= 0 && bounds.y + bounds.height <= (widget ? 320 : viewport.height) + 1, 'preview height stays within the frame');
          if (image) {
            const size = await image.boundingBox();
            assert.ok(size.width <= bounds.width + 1 && size.height <= bounds.height + 1, 'image is contained');
            if (item.file.id === 'small') assert.ok(size.width <= 64 && size.height <= 64, 'small images are not enlarged');
          }
          const downloadEvent = page.waitForEvent('download');
          await frame.getByRole(widget ? 'link' : 'button', { name: widget ? `Download ${item.file.name}` : 'Download file', exact: true }).click();
          const downloaded = await downloadEvent;
          assert.equal(downloaded.suggestedFilename(), item.file.name);
          const stream = await downloaded.createReadStream();
          const chunks = [];
          for await (const chunk of stream) chunks.push(chunk);
          assert.deepEqual(Buffer.concat(chunks), Buffer.from(item.content), 'the original file downloads intact');
          if (!widget) {
            await frame.getByRole('button', { name: 'Close preview', exact: true }).click();
            await frame.getByRole('dialog').waitFor({ state: 'detached' });
          }
        }
      }
      await page.close();
    }
    assert.equal(fixture.downloads.length, 24);
  } finally { await browser.close(); await fixture.close(); }
});
