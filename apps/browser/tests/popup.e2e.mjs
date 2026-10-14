// Production permissions and actual Chrome action-popup rendering.
import {chromium} from "playwright";
import assert from "node:assert/strict";
import {mkdtempSync,rmSync,readFileSync,writeFileSync} from "node:fs";
import {tmpdir} from "node:os";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {openActionPopup} from "./extension-popup.mjs";

const root=fileURLToPath(new URL("../",import.meta.url));
const extension=path.join(root,"frontend/public/companion");
const manifest=JSON.parse(readFileSync(path.join(extension,"manifest.json")));
assert.equal(manifest.host_permissions,undefined);
const temporary=mkdtempSync(path.join(tmpdir(),"browser-popup-e2e-"));
let context;
try {
  context=await chromium.launchPersistentContext(temporary,{headless:true,channel:"chromium",args:[`--disable-extensions-except=${extension}`,`--load-extension=${extension}`,"--enable-unsafe-extension-debugging"]});
  await context.route("https://**/*",route=>route.fulfill({contentType:"text/html",body:"<title>Fixture selected tab</title><h1>Owned popup fixture</h1>"}));
  const page=await context.newPage();
  const worker=context.serviceWorkers()[0] || await context.waitForEvent("serviceworker");
  const extensionId=worker.url().split("/")[2];
  const browser=await context.browser().newBrowserCDPSession();
  for(const url of ["chrome://extensions/","https://loopino-fixture.test/app/browser","https://www.instagram.com/fixture_user/"]) {
    await page.goto(url);await page.bringToFront();
    const popup=await openActionPopup(browser,extensionId,page.url());
    const result=await popup.evaluate("({disabled:document.querySelector('#share').disabled,hidden:document.querySelector('#share').hidden,title:document.querySelector('#tab-title').textContent,stop:document.querySelector('#stop').hidden})");
    assert.equal(result.disabled,true);assert.equal(result.hidden,true);assert.equal(result.stop,true);
    assert.equal(result.title,"A tab for your agent");
    assert.equal((await worker.evaluate(()=>chrome.storage.session.get('binding'))).binding,undefined);
    assert.equal(await popup.evaluate("document.querySelector('#connector').value"),"https://loopino.giuntitrail.com/app/browser?connector=1");
    for(const theme of ["dark","light"]) {
      await popup.send("Emulation.setEmulatedMedia",{features:[{name:"prefers-color-scheme",value:theme}]});
      await new Promise(resolve=>setTimeout(resolve,300));
      const layout=await popup.evaluate("({scheme:getComputedStyle(document.documentElement).colorScheme,overflow:document.documentElement.scrollWidth>innerWidth,height:document.body.getBoundingClientRect().height,button:getComputedStyle(document.querySelector('#open-agent')).backgroundColor})");
      assert.equal(layout.scheme,theme);assert.equal(layout.overflow,false);assert(layout.height<600);
      assert.equal(layout.button,theme === "dark" ? "rgb(255, 255, 255)" : "rgb(17, 24, 39)");
      const shot=await popup.send("Page.captureScreenshot",{format:"png"});
      writeFileSync(path.join(tmpdir(),`loopino-companion-popup-${theme}.png`),Buffer.from(shot.data,"base64"));
    }
    await popup.evaluate("document.querySelector('.settings').open=true;document.querySelector('.help').open=true;document.querySelector('#connector').focus();true");
    assert.equal(await popup.evaluate("getComputedStyle(document.querySelector('#connector')).outlineStyle"),"solid");
    assert.equal(await popup.evaluate("document.documentElement.scrollWidth>innerWidth"),false);
    await popup.close();
  }
  await page.goto('chrome://newtab/');await page.bringToFront();
  const launcher=await openActionPopup(browser,extensionId,page.url());
  const agentOpened=context.waitForEvent('page');
  await launcher.evaluate("document.querySelector('#open-agent').click();true");
  const agent=await agentOpened;await agent.waitForURL(`chrome-extension://${extensionId}/agent-tab.html`);
  await agent.bringToFront();
  const agentPopup=await openActionPopup(browser,extensionId,agent.url());
  assert.equal(await agentPopup.evaluate("document.querySelector('#share').disabled"),false);
  assert.equal(await agentPopup.evaluate("document.querySelector('#share-label').textContent"),'Connect agent tab');
  assert.equal(await agentPopup.evaluate("document.querySelector('#connector').value"),"https://loopino.giuntitrail.com/app/browser?connector=1");
  assert.equal(await worker.evaluate(()=>chrome.permissions.contains({origins:["https://www.instagram.com/*"]})),false);
  await agentPopup.evaluate("document.querySelector('#connector').value='https://loopino-fixture.test/apps/browser/';document.querySelector('#share').click();true");
  assert.match(await agentPopup.evaluate("document.querySelector('#status').textContent"),/Connection settings/u);
  assert.equal((await worker.evaluate(()=>chrome.storage.session.get('binding'))).binding,undefined);
  await agentPopup.close();
  await page.bringToFront();
  const reopen=await openActionPopup(browser,extensionId,page.url());
  const count=context.pages().length;
  await reopen.evaluate("document.querySelector('#open-agent').click();true");
  await new Promise(resolve=>setTimeout(resolve,300));
  assert.equal(context.pages().length,count,"Open agent tab reuses the existing empty tab");
  await reopen.close();
  for(const theme of ["dark","light"]) {
    await agent.emulateMedia({colorScheme:theme});await agent.setViewportSize({width:390,height:844});
    assert.equal(await agent.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await agent.screenshot({path:path.join(tmpdir(),`loopino-agent-start-${theme}.png`)});
  }
  console.log("Companion popup passed: agent-only setup from Chrome/platform pages, existing empty-tab reuse, native dark/light popup, settings focus/overflow, 390px landing, preconfigured address and invalid-address guidance.");
} finally {if(context)await context.close();rmSync(temporary,{recursive:true,force:true});}
