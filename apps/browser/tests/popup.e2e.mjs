// Production permissions: activeTab must identify the platform without pre-granted hosts.
import {chromium} from "playwright";
import assert from "node:assert/strict";
import {mkdtempSync,rmSync,readFileSync} from "node:fs";
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
  for(const url of ["chrome://extensions/","https://maverick-fixture.test/app/browser"]) {
    await page.goto(url);await page.bringToFront();
    const popup=await openActionPopup(browser,extensionId,page.url());
    const result=await popup.evaluate("({disabled:document.querySelector('#share').disabled,status:document.querySelector('#status').textContent})");
    assert.equal(result.disabled,true);assert.match(result.status,/click this extension on that tab/u);
    assert.equal((await worker.evaluate(()=>chrome.storage.session.get('binding'))).binding,undefined);
    await popup.close();
  }
  await page.goto("https://www.instagram.com/fixture_user/");await page.bringToFront();
  const popup=await openActionPopup(browser,extensionId,page.url());
  const result=await popup.evaluate("({disabled:document.querySelector('#share').disabled,title:document.querySelector('#tab-title').textContent,url:document.querySelector('#tab-url').textContent})");
  assert.equal(result.disabled,false);assert.equal(result.url,page.url());assert.equal(result.title,"Fixture selected tab");
  assert.equal(await worker.evaluate(()=>chrome.permissions.contains({origins:["https://www.instagram.com/*"]})),false);
  await popup.evaluate("document.querySelector('#connector').value='https://maverick-fixture.test/apps/browser/';document.querySelector('#share').click();true");
  assert.match(await popup.evaluate("document.querySelector('#status').textContent"),/Copy the connector address/u);
  assert.equal((await worker.evaluate(()=>chrome.storage.session.get('binding'))).binding,undefined);
  // Simulate declining the permission dialog; capture must never start.
  await popup.evaluate("chrome.permissions.request=async()=>false;document.querySelector('#connector').value='https://maverick-fixture.test/app/browser?connector=1';document.querySelector('#share').click();true");
  assert.match(await popup.evaluate("document.querySelector('#status').textContent"),/Allow access/u);
  assert.equal((await worker.evaluate(()=>chrome.storage.session.get('binding'))).binding,undefined);
  await popup.close();
  console.log("Companion popup passed with production permissions: restricted Chrome pages, Maverick rejection, selected platform via activeTab, and invalid connector guidance.");
} finally {if(context)await context.close();rmSync(temporary,{recursive:true,force:true});}
