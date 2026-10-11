// Synthetic local test surface; never attached to a user's browser or Mac.
const { chromium } = require(process.argv[2]);
const readline = require('node:readline');
const escape = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.argv[3], args: ['--no-sandbox'] });
  try {
    const page = await browser.newPage({ viewport: { width: 480, height: 520 } });
    for await (const line of readline.createInterface({ input: process.stdin })) {
      const state = JSON.parse(line);
      await page.setContent(`<html><body style="margin:0;padding:24px;background:#20232b;color:#eee;font:20px Arial">
        <h2>${escape(state.title)}</h2><div style="display:grid;gap:10px;grid-template-columns:repeat(${state.columns || 1},1fr)">
        ${state.controls.map(control => `<div style="border:1px solid #677080;border-radius:8px;padding:12px;background:${control.actionable ? '#373e4c' : '#252a34'}">
          ${escape(control.label)}${control.value !== null ? `: <b>${escape(control.value)}</b>` : ''}</div>`).join('')}
        </div></body></html>`);
      process.stdout.write((await page.screenshot({ type: 'jpeg', quality: 85, timeout: 10000 })).toString('base64') + '\n');
    }
  } finally { await browser.close(); }
})().catch(error => { process.stderr.write(error.message + '\n'); process.exitCode = 1; });
