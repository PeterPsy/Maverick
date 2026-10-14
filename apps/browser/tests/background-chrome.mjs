import assert from "node:assert/strict";
import {openActionPopup} from "./extension-popup.mjs";

export async function verifyBackgroundChrome({context,worker,page,connection,run,runMcp,api,connectorWindow,browser,extensionId,origin,frameOrigin,wait}) {
  const url="https://background-browser.example/form";
  await context.route("https://background-browser.example/**",route=>route.fulfill({contentType:"text/html",body:'<title>Background fixture</title><form><label>Name<input name="name"></label><button>Save</button></form><script>window.saved=[];document.querySelector("form").onsubmit=e=>{e.preventDefault();window.saved.push(document.querySelector("input").value);};</script>'}));
  await run("navigate",{url});
  const pages=context.pages().length;
  await connectorWindow.close();
  const snapshot=await runMcp("browser_snapshot",{});
  const ref=name=>snapshot.elements.find(element=>element.name === name)?.ref;
  await runMcp("browser_type",{ref:ref("Name"),text:"Works after Loopino closes"});
  await runMcp("browser_click",{ref:ref("Save")});
  assert.deepEqual(await page.evaluate(()=>window.saved),["Works after Loopino closes"]);
  assert.equal(context.pages().length,pages-1,"Background commands must not reopen Loopino");
  console.log(JSON.stringify({phase:"background-after-close",snapshot:true,type:true,click:true,no_reopened_tabs:true}));
  // Cover the old 120-second offline boundary with no Loopino document open.
  await new Promise(resolve=>setTimeout(resolve,125000));
  const observed=(await api({action:"companion.overview"})).connections.find(row=>row.session_id === connection.session_id);
  assert.equal(observed.status,"connected");
  assert(observed.expires_at>Date.now()/1000+90,"Heartbeats must remain live after setup closure");
  await run("snapshot");
  assert.equal(context.pages().length,pages-1);
  const stopPopup=await openActionPopup(browser,extensionId,page.url());
  await stopPopup.evaluate("document.querySelector('#share').click();true");
  await wait(async()=> (await stopPopup.evaluate("document.querySelector('#status').textContent")).startsWith("Connected in background"));
  assert.equal(context.pages().length,pages-1,"Connecting an already active source must reuse background sharing");
  assert.equal((await api({action:"companion.overview"})).connections.find(row=>row.status === "connected").session_id,connection.session_id);
  await stopPopup.evaluate("document.querySelector('#stop').click();true");
  await wait(async()=> (await api({action:"companion.overview"})).connections.find(row=>row.session_id === connection.session_id)?.status === "revoked");
  await wait(async()=> !(await worker.evaluate(()=>chrome.storage.session.get("binding"))).binding);
  assert.equal((await worker.evaluate(()=>chrome.storage.session.get("connectorSession"))).connectorSession,undefined);
  await stopPopup.detach();
  console.log(JSON.stringify({phase:"background-heartbeat-and-disconnect",same_lease_after_125_seconds:true,local_authority_cleared:true}));
  // Reconnect the same source, then close it independently of URL scope loss.
  await page.bringToFront();
  const reconnectPopup=await openActionPopup(browser,extensionId,page.url());
  await reconnectPopup.evaluate("document.querySelector('#share').click();true");
  const setup=await wait(()=>context.pages().find(candidate=>candidate.url().startsWith(`${origin}/app/browser`)));
  const frame=await wait(()=>setup.frames().find(candidate=>candidate.url().startsWith(`${frameOrigin}/apps/browser/`)));
  await frame.waitForFunction(()=>document.querySelector("#status")?.textContent.startsWith("Connected"));
  const next=await wait(async()=> (await api({action:"companion.overview"})).connections.find(row=>row.status === "connected" && row.session_id !== connection.session_id));
  await reconnectPopup.detach();
  await setup.close();await page.close();
  await wait(async()=> (await api({action:"companion.overview"})).connections.find(row=>row.session_id === next.session_id)?.status === "revoked");
  await wait(async()=> !(await worker.evaluate(()=>chrome.storage.session.get("binding"))).binding);
  assert.equal((await worker.evaluate(()=>chrome.runtime.getContexts({contextTypes:["OFFSCREEN_DOCUMENT"]}))).length,0);
  console.log(JSON.stringify({status:"passed",phase:"background-source-closed",source_capture_released:true,backend_revoked:true}));
}
