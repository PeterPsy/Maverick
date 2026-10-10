// Local visual fixture only: no connection to a user's browser or native Mac.
const { chromium } = require(process.argv[2]);
const readline = require('node:readline');

(async () => {
  const browser = await chromium.launch({
    headless: true, executablePath: process.argv[3], args: ['--no-sandbox'],
  });
  try {
    const page = await browser.newPage({ viewport: { width: 320, height: 440 } });
    for await (const line of readline.createInterface({ input: process.stdin })) {
      const state = JSON.parse(line);
      await page.setContent(`<html><body style="margin:0;background:#24242a;color:white;font:32px Arial">
        <div style="text-align:right;padding:25px 20px;height:50px">${state.value}</div>
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px;padding:8px">
        ${['AC', '±', '%', '÷', '7', '8', '9', '×', '4', '5', '6', '−', '1', '2', '3', '+', '0', '.', '=', '']
          .map(label => `<div style="text-align:center;padding:14px 0;background:#38383f;border-radius:8px">${label}</div>`).join('')}
        </div></body></html>`);
      const jpeg = await page.screenshot({ type: 'jpeg', quality: 90, timeout: 10000 });
      process.stdout.write(jpeg.toString('base64') + '\n');
    }
  } finally {
    await browser.close();
  }
})().catch(error => { process.stderr.write(error.message + '\n'); process.exitCode = 1; });
