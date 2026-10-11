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
import {request} from "node:http";
import {observe} from "../companion/dom-actions.mjs";
import {analyzeVideo} from "../companion/workflows.mjs";
import {openActionPopup} from "./extension-popup.mjs";
import {platforms} from "../companion/platforms.mjs";

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),"..");
const temporary=mkdtempSync(path.join(tmpdir(),"browser-companion-e2e-"));
const server=spawn("python3",[path.join(root,"tests/companion_fixture_server.py")],{stdio:["ignore","pipe","pipe"]});
let context;
const connectorsOnly=process.argv.includes('--connectors-only');
const realConsent=process.argv.includes('--permissions');
let mediaSummary={};
const wait=async(predicate,timeout=45000)=>{const end=Date.now()+timeout;while(Date.now()<end){const result=await predicate();if(result)return result;await new Promise(r=>setTimeout(r,150));}throw new Error("fixture_wait_timeout");};
try {
  for(const name of readdirSync(path.join(root,"companion"))) {
    if(name === "build.mjs" || name.endsWith(".test.mjs"))continue;
    assert(readFileSync(path.join(root,"companion",name)).equals(readFileSync(path.join(root,"frontend/public/companion",name))),`Rebuild Browser before testing ${name}.`);
  }
  server.stderr.on("data",chunk=>process.stderr.write(chunk));
  const lines=createInterface({input:server.stdout});
  const info=await Promise.race([new Promise(resolve=>lines.once("line",line=>resolve(JSON.parse(line)))),new Promise((_,reject)=>setTimeout(()=>reject(new Error("fixture_server_timeout")),10000))]);
  const origin=`http://maverick.localhost:${info.port}`;
  const transport=`http://127.0.0.1:${info.port}`;
  const frameOrigin=`http://af-0123456789abcdef01234567.sidecars.maverick.localhost:${info.port}`;
  // Node's fetch rewrites Host; send the exact virtual host to the local fixture.
  const fixtureFetch=(url,options={})=>new Promise((resolve,reject)=>{
    const req=request(url.replace(origin,transport).replace(frameOrigin,transport),{method:options.method || "GET",headers:{...options.headers,Host:new URL(url).host,
      ...(options.body ? {"Content-Length":Buffer.byteLength(options.body)} : {})}},response=>{
      const chunks=[];response.on("data",chunk=>chunks.push(chunk));response.on("error",reject);
      response.on("end",()=>resolve(new Response(Buffer.concat(chunks),{status:response.statusCode,headers:response.headers})));
    });
    req.on("error",reject);req.end(options.body);
  });
  const api=async body=>{const response=await fixtureFetch(`${origin}/api/apps/browser/backend`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});const result=await response.json();assert(response.ok,JSON.stringify(result));return result;};
  const extension=path.join(temporary,"extension");cpSync(path.join(root,"frontend/public/companion"),extension,{recursive:true});
  // The fast fixture pre-grants hosts. --permissions exercises the native dialog
  // with the unmodified production manifest on an isolated Xvfb display.
  const manifest=JSON.parse(readFileSync(path.join(extension,"manifest.json")));
  if(!realConsent)manifest.host_permissions=[...Object.values(platforms).flatMap(spec=>spec.hosts.map(host=>`https://${host}/*`)),"http://*.localhost/*","http://localhost/*","http://127.0.0.1/*"];
  writeFileSync(path.join(extension,"manifest.json"),JSON.stringify(manifest));
  execFileSync("espeak-ng",["-w",path.join(temporary,"voice.wav"),"Maverick browser reads video and records audio locally."]);
  execFileSync("ffmpeg",["-hide_banner","-loglevel","error","-f","lavfi","-i","testsrc=size=320x180:rate=12","-i",path.join(temporary,"voice.wav"),"-t","5","-vf","format=yuv420p","-af","apad","-c:v","libx264","-threads","1","-c:a","aac","-movflags","+faststart",path.join(temporary,"video.mp4")]);
  execFileSync("ffmpeg",["-hide_banner","-loglevel","error","-f","lavfi","-i","testsrc2=size=320x180:rate=12","-t","3","-c:v","libx264","-threads","1","-movflags","+faststart",path.join(temporary,"ended.mp4")]);
  const media=readFileSync(path.join(temporary,"video.mp4"));
  const endedMedia=readFileSync(path.join(temporary,"ended.mp4"));
  context=await chromium.launchPersistentContext(path.join(temporary,"profile"),{headless:!realConsent,channel:"chromium",ignoreDefaultArgs:["--mute-audio"],viewport:{width:1000,height:800},args:[`--disable-extensions-except=${extension}`,`--load-extension=${extension}`,"--enable-unsafe-extension-debugging","--autoplay-policy=no-user-gesture-required","--window-size=1100,740","--window-position=0,0"]});
  assert.equal((await fixtureFetch(`${origin}/apps/browser/?connector=1`)).status,403);
  assert.equal((await fixtureFetch(`${frameOrigin}/apps/browser/?connector=1`)).status,401);
  assert.equal((await context.cookies()).length,0,"Chrome starts without any Maverick or iframe session");
  const setup=await context.newPage(); await setup.goto(`${origin}/__test/download`);
  const connectorAddress=`${origin}/app/browser?connector=1`;
  const downloadPromise=setup.waitForEvent("download");
  await setup.getByRole("link",{name:"Download Companion"}).click();
  const download=await downloadPromise;assert.equal(await download.failure(),null);
  assert(readFileSync(await download.path()).equals(readFileSync(path.join(root,"frontend/package/maverick-browser-companion.zip"))));
  await setup.close();
  await context.route("https://www.instagram.com/**",route=>{
    if(route.request().url().includes("fixture-media.mp4"))return route.fulfill({contentType:"video/mp4",body:media});
    return route.fulfill({contentType:"text/html",body:`<!doctype html><html lang="it"><head><title>Fixture Instagram</title></head><body><h1>Profilo fixture</h1><p>Bio visibile</p><input type="password" value="must-not-be-read"><p hidden>hidden-secret</p><video controls muted src="/fixture-media.mp4" width="640" height="360"></video><main style="height:200px;overflow:auto"><div style="height:1400px"><a href="/p/one/">Post uno</a><a href="/reel/two/">Reel due</a><div style="margin-top:1100px"><a href="/p/three/">Post tre</a></div></div></main></body></html>`});
  });
  const instagram=await context.newPage();await instagram.goto("https://www.instagram.com/fixture_user/");await instagram.bringToFront();
  const worker=context.serviceWorkers()[0] || await context.waitForEvent("serviceworker");
  const extensionId=worker.url().split("/")[2];
  if(realConsent)await instagram.goto(`chrome-extension://${extensionId}/agent-tab.html`);
  const browser=await context.browser().newBrowserCDPSession();
  const popup=await openActionPopup(browser,extensionId,instagram.url());
  const popupEvaluate=popup.evaluate;
  await popupEvaluate(`document.querySelector('#connector').value=${JSON.stringify(connectorAddress)};document.querySelector('#share').click();true`);
  if(realConsent) {
    await new Promise(resolve=>setTimeout(resolve,1200));
    execFileSync('python3',[path.join(root,'tests/consent-dialog.py'),'Maverick agent tab']);
    await new Promise(resolve=>setTimeout(resolve,300));
    execFileSync('ffmpeg',['-hide_banner','-loglevel','error','-f','x11grab','-video_size','1366x768','-i',process.env.DISPLAY,'-frames:v','1','-y',path.join(tmpdir(),'maverick-consent.png')]);
    await popup.close();
    execFileSync('python3',[path.join(root,'tests/consent-dialog.py'),'Maverick agent tab','allow']);
    await wait(()=>worker.evaluate(()=>chrome.permissions.contains({origins:['https://www.instagram.com/*','https://www.youtube.com/*']})));
    console.log(JSON.stringify({phase:'native-consent',popup_closed_before_approval:true,first_click_continued:true}));
  }
  await wait(async()=>{
    const page=context.pages().find(page=>page.url().startsWith(`${origin}/app/browser`));if(page)return page;
    const status=await popupEvaluate("document.querySelector('#status').textContent").catch(()=>"");
    if(status && !["Connecting in Maverick", "Allow Chrome access"].some(prefix=>status.startsWith(prefix)))throw new Error(`share_failed: ${status}`);
    return context.pages().find(page=>page.url().startsWith(`${origin}/app/browser`));
  }).catch(async error=>{
    console.error(JSON.stringify({phase:"sharing",popup_status:await popupEvaluate("document.querySelector('#status').textContent").catch(()=>"closed"),worker_state:await worker.evaluate(async()=>({contexts:await chrome.runtime.getContexts({}),binding:await chrome.storage.session.get("binding")}))}));
    throw error;
  });
  const connectorWindow=context.pages().find(page=>page.url().startsWith(`${origin}/app/browser`));
  await connectorWindow.getByRole("button",{name:"Sign in as fixture user"}).click();
  await wait(()=>connectorWindow.frames().find(frame=>frame.url().startsWith(`${frameOrigin}/apps/browser/`)));
  const connector=connectorWindow.frames().find(frame=>frame.url().startsWith(`${frameOrigin}/apps/browser/`));
  await connector.waitForSelector("#stop:visible");
  await wait(async()=> (await worker.evaluate(()=>chrome.storage.session.get("binding"))).binding?.connectorDocumentId);
  assert.equal(await connector.locator("#url").inputValue(),connectorAddress);
  assert.equal(await connector.evaluate(()=>getComputedStyle(document.documentElement).colorScheme),"light");
  const consoleErrors=[];connectorWindow.on("pageerror",e=>consoleErrors.push(e.message));
  if(!realConsent)await popup.detach();
  await connectorWindow.bringToFront();
  const connection=await wait(async()=> (await api({action:"companion.overview"})).connections.find(c=>c.status === "connected"));
  console.log(JSON.stringify({phase:"chrome-connected"}));
  const run=async(action,parameters={},shared=connection)=>{
    const queued=await api({action,session_id:shared.session_id,...parameters});assert.equal(queued.status,"queued");
    const result=await wait(async()=>{const result=await api({action:"operation.get",operation_id:queued.operation_id});return ["completed","failed","cancelled","expired"].includes(result.status) ? result : null;},60000);
    assert.equal(result.status,"completed",JSON.stringify(result));return {...result.result,operation_id:queued.operation_id};
  };
  if(realConsent)await run('navigate',{url:'https://www.instagram.com/fixture_user/'});
  if(!connectorsOnly) {
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
    await endedPage.bringToFront();
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
  const capturedAudio=await fixtureFetch(`${origin}/__test/media?operation_id=${analyzed.operation_id}`);assert(capturedAudio.ok);
  writeFileSync(path.join(tmpdir(),"maverick-browser-captured.webm"),Buffer.from(await capturedAudio.arrayBuffer()));
  const cancelled=await api({action:"video.analyze",session_id:connection.session_id,frame_count:1,max_seconds:4,include_audio:true,save_evidence:false});
  await wait(()=>worker.evaluate(async()=>{const status=await chrome.runtime.sendMessage({target:"offscreen",action:"status"});return status?.recording;}));
  await api({action:"operation.cancel",operation_id:cancelled.operation_id});
  const afterCancel=await run("content.read");
  await wait(()=>worker.evaluate(async()=>{const status=await chrome.runtime.sendMessage({target:"offscreen",action:"status"});return status?.recording === false;}));
  await wait(()=>instagram.evaluate(()=>document.querySelector("video").paused));
  assert(afterCancel.text.includes("Bio visibile"));
  const collected=await run("content.collect",{urls:["https://www.instagram.com/fixture_user/"],max_items:3,max_batches:4});assert.equal(collected.items.length,3);assert.equal(collected.stop_reason,"item_limit");
  console.log(JSON.stringify({phase:"media-verified"}));
  mediaSummary={read_content:true,nested_scroll:true,distinct_video_frames:true,ended_video_recovery:true,tab_audio_bytes:analyzed.audio.size_bytes,storage_evidence_files:4,collection_items:3,cancel_audio_cleanup:true,queued_read_after_cancel:true};
  }
  assert.equal(consoleErrors.length,0,consoleErrors.join("\n"));
  // Native frontend at desktop and mobile sizes; no horizontal overflow.
  for(const viewport of [{width:1280,height:800},{width:390,height:844}]) {
    await connectorWindow.setViewportSize(viewport);assert(await connector.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await connectorWindow.screenshot({path:path.join(tmpdir(),`maverick-browser-ui-${viewport.width}.png`)});
  }
  // Exercise the agent-owned MCP surface through real Chrome/queue/Storage boundaries.
  const mcp=async(tool_name,arguments_={})=>{
    const response=await fixtureFetch(`${origin}/__test/connectors/mcp`,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({tool_name,arguments:arguments_})});
    const result=await response.json();assert(response.ok,JSON.stringify(result));return result;
  };
  await mcp('connectors_connections_refresh');
  assert.deepEqual((await mcp('platform_connectors_reference_manifest')).entity_types,[]);
  const status=await mcp('connectors_status');
  assert.equal(status.sources.length,9);
  assert(status.connections.some(c=>c.session_id === connection.session_id));
  const started=await mcp('connectors_run_start',{source:'instagram',operation:'collect',
    parameters:{username:'fixture_user',session_id:connection.session_id,max_items:3}});
  const observed=await wait(async()=>{
    const result=await mcp('connectors_run_refresh',{id:started.run.id});
    return ['completed','failed','cancelled'].includes(result.run.status) ? result.run : null;
  },90000);
  assert.equal(observed.status,'completed',JSON.stringify(observed));
  assert.equal(observed.result.items.length,3);
  assert(observed.result.items.every(item=>item.content_observed));
  assert.equal(observed.result.context_items.length,2);
  const saved=await mcp('connectors_collection_save',{run_id:observed.id,title:'Instagram acceptance collection'});
  assert(!('deep_link' in observed));
  assert(!('deep_link' in saved.collection));
  const retained=await mcp('connectors_collection_get',{id:saved.collection.id});
  assert.equal(retained.collection.items.length,5);
  const refs=await mcp('platform_connectors_reference_search',{query:'Instagram acceptance'});
  assert.equal(refs.results[0].entity_id,saved.collection.id);
  assert(!('deep_link' in refs.results[0]));
  const resolved=await mcp('platform_connectors_reference_resolve',{entity_type:'collection',entity_id:saved.collection.id});
  assert.equal(resolved.payload.id,saved.collection.id);
  const exporting=await mcp('connectors_collection_export',{id:saved.collection.id,format:'markdown'});
  const exportedRun=(await mcp('connectors_run_get',{id:exporting.run.id})).run;
  assert.equal(exportedRun.status,'completed',JSON.stringify(exportedRun));
  assert(exportedRun.result.file.file_id);
  const exported=await fixtureFetch(`${origin}/${exportedRun.result.file.workspace_relative_path}`);
  assert(exported.ok);assert((await exported.text()).includes('Instagram acceptance collection'));
  assert.equal((await fixtureFetch(`${origin}/apps/platform-connectors/`)).status,404);
  assert.equal(consoleErrors.length,0,consoleErrors.join('\n'));
  await instagram.goto("https://www.instagram.com/accounts/login/");
  await wait(async()=>{const overview=await api({action:"companion.overview"});return overview.connections.find(c=>c.session_id === connection.session_id)?.status === "revoked";});
  await context.route("https://x.com/**",route=>route.fulfill({contentType:"text/html",body:"<title>Fixture X</title><h1>X research fixture</h1>"}));
  await context.route("https://unapproved-fixture.test/**",route=>route.fulfill({contentType:"text/html",body:"<h1>Out of scope</h1>"}));
  await instagram.bringToFront();
  const launcher=await openActionPopup(browser,extensionId,instagram.url());
  await launcher.evaluate("document.querySelector('#open-agent').click();true");
  const agent=await wait(()=>context.pages().find(page=>page.url().endsWith("/agent-tab.html")));
  await agent.bringToFront();
  const agentPopup=await openActionPopup(browser,extensionId,agent.url());
  assert.equal(await agentPopup.evaluate("document.querySelector('#share').textContent"),"Connect agent tab");
  assert.equal(await agentPopup.evaluate("document.querySelector('#reuse').checked"),true);
  // The existing Maverick instance can be on another native app when reconnecting.
  await connectorWindow.evaluate(()=>history.replaceState({},"","/app/chat"));
  const reused=connectorWindow.waitForEvent('framenavigated',{predicate:frame=>frame === connectorWindow.mainFrame()});
  await agentPopup.evaluate(`document.querySelector('#connector').value=${JSON.stringify(connectorAddress)};document.querySelector('#share').click();true`);
  // Native-consent mode already granted all six hosts on the initial agent tab;
  // the next explicit share must reuse those permissions without another prompt.
  await reused;
  const agentWindow=connectorWindow;
  assert.equal(context.pages().filter(page=>page.url().startsWith(`${origin}/app/browser`)).length,1,'Sharing a new agent tab must reuse the existing Browser bridge.');
  const agentFrame=await wait(()=>agentWindow.frames().find(frame=>frame.url().startsWith(`${frameOrigin}/apps/browser/`)));
  await agentFrame.waitForSelector('#stop:visible');
  const agentConnection=await wait(async()=> (await api({action:'companion.overview'})).connections.find(c=>c.status === 'connected' && c.sharing_mode === 'agent_tab'));
  assert.equal(agentConnection.url,"");assert.deepEqual(agentConnection.allowed_platforms,Object.keys(platforms));
  // Native rail navigation can remove connector=1 and hide the retained Browser
  // frame. The authorized shell tab/document remains the bridge in both cases.
  await agentWindow.evaluate(()=>history.replaceState({},"","/app/browser"));
  assert.equal((await run('tabs',{},agentConnection)).tabs[0].url,"");
  await agentWindow.evaluate(frameOrigin=>{
    history.pushState({},"","/app/chat");
    const frame=document.querySelector('iframe');frame.style.display='none';
    frame.contentWindow.postMessage({type:'maverick.app.visibility-changed',app_id:'browser',visible:false},frameOrigin);
  },frameOrigin);
  assert.equal((await run('tabs',{},agentConnection)).tabs[0].url,"");
  await run('navigate',{url:'https://x.com/home/'},agentConnection);
  assert((await run('content.read',{},agentConnection)).text.includes('X research fixture'));
  await agentWindow.evaluate(frameOrigin=>{
    history.pushState({},"","/app/browser");
    const frame=document.querySelector('iframe');frame.style.display='';
    frame.contentWindow.postMessage({type:'maverick.app.visibility-changed',app_id:'browser',visible:true},frameOrigin);
  },frameOrigin);
  const agentShot=await run('screenshot',{},agentConnection);
  assert(Buffer.from(agentShot.base64,'base64').subarray(0,3).equals(Buffer.from([255,216,255])));
  writeFileSync(path.join(tmpdir(),'maverick-agent-x-screenshot.jpg'),Buffer.from(agentShot.base64,'base64'));
  await run('navigate',{url:'https://www.instagram.com/'},agentConnection);
  assert((await run('content.read',{},agentConnection)).text.includes('Bio visibile'));
  if(!connectorsOnly) {
    const a=await run('video.frame',{time_seconds:0.5},agentConnection),b=await run('video.frame',{time_seconds:3},agentConnection);
    assert.notEqual(a.base64,b.base64,'Agent-tab capture must reflect the presented seek, not a stale captured frame.');
    assert(Math.abs(a.width/a.height-16/9)<0.02,'Video crops must retain their source aspect ratio when tab capture letterboxes the viewport.');
    writeFileSync(path.join(tmpdir(),'maverick-agent-video-frame.jpg'),Buffer.from(a.base64,'base64'));
    const agentVideo=await run('video.analyze',{frame_count:2,max_seconds:2,include_audio:true,save_evidence:false},agentConnection);
    assert.equal(agentVideo.frames.length,2);assert(agentVideo.audio.size_bytes>1000);
  }
  await mcp('connectors_connections_refresh');
  assert((await mcp('connectors_status')).connections.some(c=>c.session_id === agentConnection.session_id && c.sharing_mode === 'agent_tab'));
  await agent.goto('https://unapproved-fixture.test/');
  await wait(async()=> (await api({action:'companion.overview'})).connections.find(c=>c.session_id === agentConnection.session_id)?.status === 'revoked');
  const stopped=(await api({action:'companion.overview'})).connections.find(c=>c.session_id === agentConnection.session_id);
  assert(stopped.stop_reason && stopped.stop_reason !== 'user_stopped','Automatic revocation must retain a diagnostic cause.');
  const stoppedMessage=await agentFrame.locator('#status').textContent();
  assert.match(stoppedMessage,/Sharing stopped:/u);
  console.log(JSON.stringify({phase:'scope-stopped',reason:stopped.stop_reason,message:stoppedMessage}));
  console.log(JSON.stringify({status:"passed",real_chromium:true,fresh_chrome_login:true,exact_connector_document:true,anonymous_download_verified:true,...mediaSummary,empty_agent_tab:true,cross_platform_navigation:true,cross_platform_screenshot:true,agent_scope_revocation:true,connectors_read_items:3,connectors_context_pages:2,connectors_collection_saved:true,connectors_storage_export_verified:true,connectors_mcp_workflow:true,connectors_frontend_absent:true,scope_revocation:true,browser_desktop_mobile_layout:true,instagram_access_verified:false}));
}finally {
  if(context)await context.close();
  if(server.exitCode === null && server.signalCode === null){const exited=new Promise(resolve=>server.once("exit",resolve));server.kill("SIGTERM");await exited;}
  rmSync(temporary,{recursive:true,force:true});
}
