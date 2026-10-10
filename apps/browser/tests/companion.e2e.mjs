// Real Chromium/MV3 capture over an intercepted Instagram-shaped fixture.
// This verifies the implementation, never access to Instagram or a real profile.
import {chromium} from "playwright";
import assert from "node:assert/strict";
import {spawn,execFileSync} from "node:child_process";
import {mkdtempSync,cpSync,readFileSync,writeFileSync,rmSync,readdirSync} from "node:fs";
import {tmpdir} from "node:os";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {createInterface} from "node:readline";
import {observe} from "../companion/dom-actions.mjs";
import {analyzeVideo} from "../companion/workflows.mjs";

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),"..");
const temporary=mkdtempSync(path.join(tmpdir(),"browser-companion-e2e-"));
const server=spawn("python3",[path.join(root,"tests/companion_fixture_server.py")],{stdio:["ignore","pipe","pipe"]});
let context;
const wait=async(predicate,timeout=20000)=>{const end=Date.now()+timeout;while(Date.now()<end){const result=await predicate();if(result)return result;await new Promise(r=>setTimeout(r,100));}throw new Error("fixture_wait_timeout");};
try {
  for(const name of readdirSync(path.join(root,"companion"))) {
    if(name === "build.mjs" || name.endsWith(".test.mjs"))continue;
    assert(readFileSync(path.join(root,"companion",name)).equals(readFileSync(path.join(root,"frontend/public/companion",name))),`Rebuild Browser before testing ${name}.`);
  }
  server.stderr.on("data",chunk=>process.stderr.write(chunk));
  const lines=createInterface({input:server.stdout});
  const info=await Promise.race([new Promise(resolve=>lines.once("line",line=>resolve(JSON.parse(line)))),new Promise((_,reject)=>setTimeout(()=>reject(new Error("fixture_server_timeout")),10000))]);
  const origin=`http://127.0.0.1:${info.port}`;
  const api=async body=>{const response=await fetch(`${origin}/api/apps/browser/backend`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});const result=await response.json();assert(response.ok,JSON.stringify(result));return result;};
  const extension=path.join(temporary,"extension");cpSync(path.join(root,"frontend/public/companion"),extension,{recursive:true});
  // Only the fixture manifest pre-grants hosts, avoiding the permission dialog.
  // The production package still has no permanent host permissions.
  const manifest=JSON.parse(readFileSync(path.join(extension,"manifest.json")));
  manifest.host_permissions=["https://www.instagram.com/*","http://127.0.0.1/*"];
  writeFileSync(path.join(extension,"manifest.json"),JSON.stringify(manifest));
  execFileSync("espeak-ng",["-w",path.join(temporary,"voice.wav"),"Maverick browser reads video and records audio locally."]);
  execFileSync("ffmpeg",["-hide_banner","-loglevel","error","-f","lavfi","-i","testsrc=size=320x180:rate=12","-i",path.join(temporary,"voice.wav"),"-t","5","-vf","format=yuv420p","-af","apad","-c:v","libx264","-threads","1","-c:a","aac","-movflags","+faststart",path.join(temporary,"video.mp4")]);
  execFileSync("ffmpeg",["-hide_banner","-loglevel","error","-f","lavfi","-i","testsrc2=size=320x180:rate=12","-t","3","-c:v","libx264","-threads","1","-movflags","+faststart",path.join(temporary,"ended.mp4")]);
  const media=readFileSync(path.join(temporary,"video.mp4"));
  const endedMedia=readFileSync(path.join(temporary,"ended.mp4"));
  context=await chromium.launchPersistentContext(path.join(temporary,"profile"),{headless:true,channel:"chromium",ignoreDefaultArgs:["--mute-audio"],viewport:{width:1000,height:800},args:[`--disable-extensions-except=${extension}`,`--load-extension=${extension}`,"--enable-unsafe-extension-debugging","--autoplay-policy=no-user-gesture-required"]});
  await context.route("https://www.instagram.com/**",route=>{
    if(route.request().url().includes("fixture-media.mp4"))return route.fulfill({contentType:"video/mp4",body:media});
    return route.fulfill({contentType:"text/html",body:`<!doctype html><html lang="it"><head><title>Fixture Instagram</title></head><body><h1>Profilo fixture</h1><p>Bio visibile</p><input type="password" value="must-not-be-read"><p hidden>hidden-secret</p><video controls muted src="/fixture-media.mp4" width="640" height="360"></video><main style="height:200px;overflow:auto"><div style="height:1400px"><a href="/p/one/">Post uno</a><a href="/reel/two/">Reel due</a><div style="margin-top:1100px"><a href="/p/three/">Post tre</a></div></div></main></body></html>`});
  });
  const instagram=await context.newPage();await instagram.goto("https://www.instagram.com/fixture_user/");await instagram.bringToFront();
  const worker=context.serviceWorkers()[0] || await context.waitForEvent("serviceworker");
  const extensionId=worker.url().split("/")[2];
  const browser=await context.browser().newBrowserCDPSession();
  const targets=(await browser.send("Target.getTargets",{filter:[{type:"tab"},{exclude:true}]})).targetInfos;
  const target=targets.find(t=>t.url.includes("instagram.com"));
  await browser.send("Extensions.triggerAction",{id:extensionId,targetId:target.targetId});
  // Chrome's action popup is a DevTools target outside Playwright's page list.
  const popup=await wait(async()=> (await browser.send("Target.getTargets",{filter:[{}]})).targetInfos.find(t=>t.type === "page" && t.url.endsWith("/popup.html")));
  const {sessionId}=await browser.send("Target.attachToTarget",{targetId:popup.targetId,flatten:false});
  let requestId=0;
  const popupEvaluate=async expression=>{
    const id=++requestId;
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{browser.off("Target.receivedMessageFromTarget",received);reject(new Error("popup_evaluation_timeout"));},10000);
      function received(event) {
        if(event.sessionId !== sessionId)return;const response=JSON.parse(event.message);if(response.id !== id)return;
        clearTimeout(timer);browser.off("Target.receivedMessageFromTarget",received);
        if(response.error || response.result?.exceptionDetails)reject(new Error(JSON.stringify(response)));else resolve(response.result?.result?.value);
      }
      browser.on("Target.receivedMessageFromTarget",received);
      browser.send("Target.sendMessageToTarget",{sessionId,message:JSON.stringify({id,method:"Runtime.evaluate",params:{expression,returnByValue:true,awaitPromise:true,userGesture:true}})}).catch(reject);
    });
  };
  await wait(()=>popupEvaluate("typeof document.querySelector('#share')?.onclick === 'function'"));
  await popupEvaluate(`document.querySelector('#connector').value=${JSON.stringify(`${origin}/apps/browser/?connector=1`)};document.querySelector('#share').click();true`);
  await wait(async()=>{
    const page=context.pages().find(page=>page.url().startsWith(`${origin}/apps/browser/`));if(page)return page;
    const status=await popupEvaluate("document.querySelector('#status').textContent").catch(()=>"");
    if(status && !status.startsWith("Scheda condivisa"))throw new Error(`share_failed: ${status}`);
    return context.pages().find(page=>page.url().startsWith(`${origin}/apps/browser/`));
  }).catch(async error=>{
    console.error(JSON.stringify({phase:"sharing",popup_status:await popupEvaluate("document.querySelector('#status').textContent").catch(()=>"closed"),worker_state:await worker.evaluate(async()=>({contexts:await chrome.runtime.getContexts({}),binding:await chrome.storage.session.get("binding")}))}));
    throw error;
  });
  const connector=context.pages().find(page=>page.url().startsWith(`${origin}/apps/browser/`));
  const consoleErrors=[];connector.on("pageerror",e=>consoleErrors.push(e.message));
  await connector.locator("#connect").click();
  const connection=await wait(async()=> (await api({action:"companion.overview"})).connections.find(c=>c.status === "connected"));
  const run=async(action,parameters={})=>{
    const queued=await api({action,session_id:connection.session_id,...parameters});assert.equal(queued.status,"queued");
    const result=await wait(async()=>{const result=await api({action:"operation.get",operation_id:queued.operation_id});return ["completed","failed","cancelled","expired"].includes(result.status) ? result : null;},60000);
    assert.equal(result.status,"completed",JSON.stringify(result));return {...result.result,operation_id:queued.operation_id};
  };
  const content=await run("content.read");assert(content.text.includes("Bio visibile"));assert(!content.text.includes("must-not-be-read"));assert(!content.text.includes("hidden-secret"));assert.equal(content.videos[0].duration_seconds,5);
  const scrolling=await run("scroll",{pixels:600});assert.equal(scrolling.target,"rendered_container");assert(scrolling.moved);
  const first=await run("video.frame",{time_seconds:0.5});assert(Buffer.from(first.base64,"base64").subarray(0,3).equals(Buffer.from([255,216,255])));
  const second=await run("video.frame",{time_seconds:3});
  assert(first.time_seconds>=0.45 && first.time_seconds<0.9,`First captured time: ${first.time_seconds}`);
  assert(second.time_seconds>=2.95 && second.time_seconds<3.4,`Second captured time: ${second.time_seconds}`);
  writeFileSync(path.join(tmpdir(),"maverick-browser-frame-1.jpg"),Buffer.from(first.base64,"base64"));
  writeFileSync(path.join(tmpdir(),"maverick-browser-frame-2.jpg"),Buffer.from(second.base64,"base64"));
  assert(first.base64 !== second.base64,"Different video seeks must produce different captured frames.");
  // Exercise the actual DOM adapter and video workflow on ended media in a
  // separate Chromium page, independent of the shared tab's live audio clock.
  const endedPage=await context.newPage();
  try {
    await endedPage.setContent(`<video controls width="640" height="360" src="data:video/mp4;base64,${endedMedia.toString("base64")}"></video>`);
    await wait(()=>endedPage.evaluate(()=>document.querySelector("video").readyState>=2));
    await endedPage.evaluate(()=>{const video=document.querySelector("video");video.currentTime=video.duration;});
    await wait(()=>endedPage.evaluate(()=>{const video=document.querySelector("video");return video.ended && !video.seeking;}));
    const dom=(action,p)=>endedPage.evaluate(`(${observe.toString()})(${JSON.stringify(action)},${JSON.stringify(p)})`).then(result=>{
      assert(!result.error,JSON.stringify(result));return result;
    });
    const prepared=await dom("video.prepare",{});
    assert(prepared.presented_time_seconds>=0 && prepared.presented_time_seconds<0.4,"Default capture must recover from an ended video.");
    await dom("video.restore",{});
    const endedAnalysis=await analyzeVideo({check(){},dom,async capture(){return {base64:(await endedPage.screenshot({type:"jpeg"})).toString("base64")};}},
      {frame_count:2,max_seconds:2,include_audio:false});
    assert.equal(endedAnalysis.frames.length,2);
    assert(await endedPage.evaluate(()=>{const video=document.querySelector("video");return video.paused && Math.abs(video.currentTime-video.duration)<0.01;}),"Analysis must restore the original ended state.");
  } finally {await endedPage.close();}
  const analyzed=await run("video.analyze",{frame_count:3,max_seconds:4,include_audio:true,save_evidence:true});
  assert.equal(analyzed.frames.length,3);assert(analyzed.frames.every(f=>f.storage?.file_id && !f.base64));assert(analyzed.audio.storage?.file_id);assert(analyzed.audio.size_bytes>5000);assert.equal(analyzed.transcription.status,"unavailable");
  const capturedAudio=await fetch(`${origin}/__test/media?operation_id=${analyzed.operation_id}`);assert(capturedAudio.ok);
  writeFileSync(path.join(tmpdir(),"maverick-browser-captured.webm"),Buffer.from(await capturedAudio.arrayBuffer()));
  const cancelled=await api({action:"video.analyze",session_id:connection.session_id,frame_count:1,max_seconds:4,include_audio:true,save_evidence:false});
  await wait(()=>worker.evaluate(async()=>{const status=await chrome.runtime.sendMessage({target:"offscreen",action:"status"});return status?.recording;}));
  await api({action:"operation.cancel",operation_id:cancelled.operation_id});
  const afterCancel=await run("content.read");
  await wait(()=>worker.evaluate(async()=>{const status=await chrome.runtime.sendMessage({target:"offscreen",action:"status"});return status?.recording === false;}));
  await wait(()=>instagram.evaluate(()=>document.querySelector("video").paused));
  assert(afterCancel.text.includes("Bio visibile"));
  const collected=await run("instagram.collect",{username:"fixture_user",max_items:3,max_batches:4,include_reels:false});assert.equal(collected.items.length,3);assert.equal(collected.stop_reason,"item_limit");
  assert.equal(consoleErrors.length,0,consoleErrors.join("\n"));
  // Native frontend at desktop and mobile sizes; no horizontal overflow.
  for(const viewport of [{width:1280,height:800},{width:390,height:844}]) {
    await connector.setViewportSize(viewport);assert(await connector.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await connector.screenshot({path:path.join(tmpdir(),`maverick-browser-ui-${viewport.width}.png`)});
  }
  await instagram.goto("https://www.instagram.com/accounts/login/");
  await wait(async()=>{const overview=await api({action:"companion.overview"});return overview.connections.find(c=>c.session_id === connection.session_id)?.status === "revoked";});
  console.log(JSON.stringify({status:"passed",real_chromium:true,read_content:true,nested_scroll:true,distinct_video_frames:true,ended_video_recovery:true,tab_audio_bytes:analyzed.audio.size_bytes,storage_evidence_files:4,collection_items:3,cancel_audio_cleanup:true,queued_read_after_cancel:true,scope_revocation:true,desktop_mobile_layout:true,instagram_access_verified:false}));
}finally {
  if(context)await context.close();
  if(server.exitCode === null && server.signalCode === null){const exited=new Promise(resolve=>server.once("exit",resolve));server.kill("SIGTERM");await exited;}
  rmSync(temporary,{recursive:true,force:true});
}
