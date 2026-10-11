import { expect, test } from '@playwright/test';

for (const width of [390, 800, 1280]) {
  test(`Mail toolbar stays on one row and expands search at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto('/apps/chat/tests/mail-toolbar/index.html');
    const toolbar = page.locator('.toolbar');
    const search = toolbar.getByRole('button', { name: 'Search in Mail' });
    const refresh = toolbar.getByRole('button', { name: 'Load more mail' });
    await expect(search).toBeVisible();
    const searchBox = (await search.boundingBox())!;
    const refreshBox = (await refresh.boundingBox())!;
    expect(Math.abs(searchBox.y - refreshBox.y)).toBeLessThan(1);
    expect((await toolbar.boundingBox())!.height).toBeLessThan(70);
    const style = await refresh.evaluate((element) => {
      const css = getComputedStyle(element);
      return { border: css.borderWidth, background: css.backgroundColor };
    });
    expect(style).toEqual({ border: '0px', background: 'rgba(0, 0, 0, 0)' });
    await refresh.click();
    await expect(page.getByTestId('refreshes')).toHaveText('1');
    await search.click();
    const input = toolbar.getByRole('searchbox', { name: 'Search in Mail' });
    await expect(input).toBeFocused();
    await expect(refresh).toHaveCount(0);
    await expect(toolbar.locator('.mail-page-controls')).toHaveCount(0);
    expect((await toolbar.locator('.mail-search').boundingBox())!.width).toBeGreaterThan(width - 30);
    await input.fill('invoice');
    await input.press('Escape');
    await expect(search).toBeFocused();
    await expect(input).toHaveCount(0);
    await expect(page.getByTestId('query')).toHaveText('invoice');
    await search.click();
    await expect(input).toHaveValue('invoice');
    await toolbar.getByRole('button', { name: 'Close search' }).click();
    await expect(search).toBeVisible();
    await search.click();
    await page.getByTestId('outside').click();
    await expect(input).toHaveCount(0);
    await expect(refresh).toBeVisible();
  });
}
