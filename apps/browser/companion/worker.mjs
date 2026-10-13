import {boundedCommand,connectorUrl,connectorOrigins,sharedTabUrl,sameConnector,sameConnectorFrame} from "./scope.mjs";
import {platforms} from "./platforms.mjs";
import {attachConnectorFrame} from "./connector-frame.mjs";
import {openConnectorWindow} from "./connector-window.mjs";
import {createShareSetup} from "./share-setup.mjs";
import {createAgentTabRegistry} from "./agent-tab.mjs";
import {selectedAgentTab} from "./setup.mjs";
import {interactionActions} from "./interaction-inputs.mjs";
import {createInteractionController} from "./interaction-controller.mjs";
import {createConnectorSession} from "./connector-session.mjs";
import {observe} from "./dom-actions.mjs";
import {collectContent,analyzeVideo} from "./workflows.mjs";

let busy=null;
let lastScreenshotAt=0;
let attaching;
const activationGenerations=new Map();
chrome.tabs.onActivated.addListener(event=>{activationGenerations.set(event.windowId,(activationGenerations.get(event.windowId) || 0)+1);});
chrome.windows.onRemoved.addListener(id=>activationGenerations.delete(id));
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const binding=async()=> (await chrome.storage.session.get("binding")).binding;
const agentTabs=createAgentTabRegistry(chrome,chrome.runtime.getURL("agent-tab.html"));
const sharedUrl=(value,b)=>sharedTabUrl(value,b,chrome.runtime.getURL("agent-tab.html"));
const attach=b=>{
  if(attaching)return attaching;
  attaching=attachConnectorFrame(b,binding).finally(()=>{attaching=null;});return attaching;
};
async function capture(action,parameters={}) {
  const result=await chrome.runtime.sendMessage({target:"offscreen",action,parameters});
  if(!result || result.error)throw new Error(result?.error || "capture_unavailable");return result;
}
async function screenshot(b,parameters) {
  await scope(b);
  const tab=await chrome.tabs.update(b.tabId,{active:true});
  await delay(Math.max(100,600-(Date.now()-lastScreenshotAt)));
  await scope(b);
  if (b.allowedPlatforms?.length) return capture("stream.frame",parameters);
  const active=await chrome.tabs.query({active:true,windowId:tab.windowId});
  if(active[0]?.id !== b.tabId)throw new Error("shared_tab_not_active");
  const generation=activationGenerations.get(tab.windowId);
  lastScreenshotAt=Date.now();
  const image_data_url=await chrome.tabs.captureVisibleTab(tab.windowId,{format:"jpeg",quality:80});
  const observed=await scope(b);
  const after=await chrome.tabs.query({active:true,windowId:tab.windowId});
  if(after[0]?.id !== b.tabId || observed.windowId !== tab.windowId || activationGenerations.get(tab.windowId) !== generation)throw new Error("active_tab_changed_during_capture");
  return capture("frame",{...parameters,image_data_url});
}
let stopQueue=Promise.resolve(),shareEpoch=0;
function stop(reason="sharing_stopped",expectedSharingId) {
  if(!expectedSharingId)shareEpoch++;
  const pending=stopQueue.catch(()=>{}).then(()=>stopCurrent(reason,expectedSharingId));
  stopQueue=pending;return pending;
}
async function stopCurrent(reason,expectedSharingId) {
  const shared=await binding();
  if(expectedSharingId && shared?.sharingId !== expectedSharingId)return {status:"obsolete"};
  if(busy)busy.cancelled=true;
  if(shared)await dom(shared,"video.restore",{},busy?.expected).catch(()=>{});
  if(shared && (await binding())?.sharingId !== shared.sharingId)return {status:"obsolete"};
  await chrome.storage.session.remove("binding");
  await connectorSession.clear();
  await chrome.storage.session.remove("interactionSnapshot");
  if(shared)await chrome.tabs.update(shared.connectorTabId,{autoDiscardable:shared.connectorAutoDiscardable ?? true}).catch(()=>{});
  await chrome.alarms.clear("connector-wake");
  await capture("stop").catch(()=>{});
  const contexts=await chrome.runtime.getContexts({contextTypes:["OFFSCREEN_DOCUMENT"]});
  if(contexts.length)await chrome.offscreen.closeDocument().catch(()=>{});
  await chrome.action.setBadgeText({text:""});
  return {status:"revoked",reason};
}
async function scope(b) {
  const current=await binding();
  if(!b || current?.tabId !== b.tabId || current?.sharingId !== b.sharingId)throw new Error("sharing_revoked");
  const tab=await chrome.tabs.get(b.tabId);
  sharedUrl(tab.url,b);
  return tab;
}
async function dom(b,action,parameters={},expected) {
  const tab=await scope(b);
  if (!sharedUrl(tab.url,b)) throw new Error("agent_tab_empty");
  if(expected && sharedUrl(tab.url,b) !== expected.url)throw new Error("shared_tab_changed_during_operation");
  const target={tabId:b.tabId,...(expected?.documentId ? {documentIds:[expected.documentId]} : {})};
  const loaded=await chrome.scripting.executeScript({target,files:["reader.js"]});
  if(expected && !expected.documentId)expected.documentId=loaded[0]?.documentId;
  const results=await chrome.scripting.executeScript({target:{tabId:b.tabId,...(expected?.documentId ? {documentIds:[expected.documentId]} : {})},func:observe,args:[action,{...parameters,website_scope:b.websiteScope}]});
  const after=await scope(b);
  if(expected && sharedUrl(after.url,b) !== expected.url)throw new Error("shared_tab_changed_during_operation");
  if(results[0]?.result == null)throw new Error("observation_unavailable");
  if(results[0].result.error)throw new Error(results[0].result.detail || results[0].result.error);
  return results[0].result;
}
async function navigate(b,url) {
  await scope(b);await chrome.tabs.update(b.tabId,{url:sharedUrl(url,b)});
  const end=Date.now()+15000;
  while(Date.now()<end) {
    const tab=await scope(b);
    if(tab.status === "complete" && sharedUrl(tab.url,b) === sharedUrl(url,b)) {
      await delay(1000);return {url:sharedUrl(tab.url,b),title:tab.title};
    }
    await delay(100);
  }
  throw new Error("navigation_timeout");
}
async function execute(b,command) {
  boundedCommand(command,b);
  const initial=await scope(b);
  if(busy)throw new Error("operation_already_running");
  const task={id:command.operation_id,cancelled:false};busy=task;
  let retained={};
  const expected={url:sharedUrl(initial.url,b),documentId:null};
  task.expected=expected;
  const check=()=>{if(task.cancelled)throw new Error("operation_cancelled");if(Date.now()/1000>command.expires_at)throw new Error("operation_expired");};
  const fixedDom=async(a,p)=>{
    check();
    if(["video.prepare","video.seek"].includes(a)) {
      const tab=await chrome.tabs.update(b.tabId,{active:true});
      await chrome.windows.update(tab.windowId,{focused:true});
    }
    return dom(b,a,p,expected);
  };
  const adapter={check,delay,dom:fixedDom,read:p=>fixedDom("content.read",p),scroll:p=>fixedDom("scroll",p),
    navigate:async url=>{check();const result=await navigate(b,url);expected.url=sharedUrl(url,b);expected.documentId=null;return result;},
    capture:async(a,p)=>{check();await fixedDom("wait_for",{});const result=a === "frame" ? await screenshot(b,p) : await capture(a,p);await fixedDom("wait_for",{});return result;},
    cleanup:async(a,p)=>{await scope(b);return a === "video.restore" ? dom(b,a,p,expected) : capture(a,p);}};
  try {
    retained=await connectorSession.read(b);
    if(retained.completion) {
      if(retained.completion.operation_id === command.operation_id && retained.completion.lease_id === command.lease_id)return retained.completion.result;
      throw new Error("previous_completion_pending");
    }
    check();const p=command.parameters || {};let result;
    const controls=createInteractionController(chrome,{scope,check,delay});
    if(command.action === "navigate")result=await adapter.navigate(p.url);
    else if(interactionActions.has(command.action))result=await controls.run(b,command.action,p);
    else if(command.action === "snapshot" && b.accessMode === "interactive")result={...await adapter.dom("snapshot",p),...await controls.snapshot(b,p)};
    else if(command.action === "content.collect")result=await collectContent(adapter,p);
    else if(command.action === "video.analyze")result=await analyzeVideo(adapter,p);
    else if(command.action === "screenshot")result=await adapter.capture("frame",{});
    else if(command.action === "video.frame") {
      try{const timing=await adapter.dom("video.prepare",p);result={...await adapter.capture("frame",timing),time_seconds:timing.presented_time_seconds,requested_time_seconds:p.time_seconds ?? null,video_index:p.video_index ?? 0};}
      finally{await dom(b,"video.restore",p,expected).catch(()=>{});}
    } else if(command.action === "tabs") {const tab=await scope(b);result={tabs:[{url:sharedUrl(tab.url,b),title:tab.title,shared:true}]};}
    else result=await adapter.dom(command.action,p);
    check();const tab=await scope(b);
    const completed={...result,source_url:sharedUrl(tab.url,b),observed_at:new Date().toISOString()};
    await connectorSession.finish(b,command,completed,retained.lease?.connection.session_id);
    return completed;
  } catch(error) {
    if(!retained.completion)await connectorSession.finish(b,command,{error:"chrome_observation_failed",detail:error.message},retained.lease?.connection.session_id).catch(()=>{});
    throw error;
  } finally {if(busy===task)busy=null;}
}
async function share(message) {
  const url=connectorUrl(message.url);const tab=await chrome.tabs.get(message.tabId);
  if (message.agentTab !== true) throw new Error("agent_tab_required");
  selectedAgentTab(tab,chrome.runtime.getURL("agent-tab.html"),await agentTabs.get());
  const approved=Object.keys(platforms);
  if (!await chrome.permissions.contains({origins:[...connectorOrigins(url),"https://*/*"]})) throw new Error("permission_denied");
  await chrome.storage.local.set({connectorUrl:url.href});
  const identity=await agentTabs.remember(tab);
  await stop();
  const epoch=shareEpoch;
  try {
    await chrome.offscreen.createDocument({url:"offscreen.html",reasons:["USER_MEDIA"],justification:"Read-only capture of the single platform tab explicitly shared by the user."});
    // Chrome 116+ permits worker-issued stream IDs in the offscreen document.
    const streamId=await chrome.tabCapture.getMediaStreamId({targetTabId:tab.id});
    await capture("start",{streamId});
    const connector=await openConnectorWindow(url,{sourceTabId:tab.id,reuse:message.reuseConnector !== false});
    if(epoch!==shareEpoch)throw new Error("sharing_revoked");
    await chrome.tabs.update(connector.id,{autoDiscardable:false});
    await chrome.storage.session.set({binding:{sharingId:crypto.randomUUID(),agentTabId:identity.id,accessMode:"interactive",websiteScope:"https",autoConnect:true,tabId:tab.id,connectorTabId:connector.id,connectorAutoDiscardable:connector.autoDiscardable ?? true,origin:url.origin,path:url.pathname,frameDomain:url.searchParams.get("frame_domain") || url.hostname,platform:null,allowedPlatforms:approved}});
    if(epoch!==shareEpoch)throw new Error("sharing_revoked");
    await chrome.alarms.create("connector-wake",{periodInMinutes:0.5});
    await chrome.action.setBadgeText({text:"AGENT"});await chrome.action.setBadgeBackgroundColor({color:"#171717"});
    // A tab may finish loading before onUpdated observes the stored binding.
    const loaded=await chrome.tabs.get(connector.id);
    if(loaded.status === "complete")await chrome.scripting.executeScript({target:{tabId:connector.id,frameIds:[0]},files:["shell-bridge.js"]});
    return {status:"shared"};
  } catch(error) {await stop();throw error;}
}
const beginShare=createShareSetup(share);
const connectorSession=createConnectorSession(chrome,binding);
chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  if(sender.id !== chrome.runtime.id || message.target !== "worker")return;
  (async()=>{
    if(message.action === "share") {
      if(sender.url !== chrome.runtime.getURL("popup.html"))throw new Error("popup_gesture_required");
      return beginShare(message);
    }
    if(message.action === "agent.open" && sender.url === chrome.runtime.getURL("popup.html")) {
      const tab=await agentTabs.open();
      return {tabId:tab.id};
    }
    if(message.action === "stop" && sender.url === chrome.runtime.getURL("popup.html"))return stop();
    const b=await binding();
    if(!b || !sender.tab || !sameConnector(sender.tab,b))throw new Error("connector_scope_required");
    if(message.action === "connector.refresh") {
      if(sender.frameId !== 0 || sender.url !== sender.tab.url)throw new Error("connector_scope_required");
      return attach(b);
    }
    if(!sameConnectorFrame(sender,b))throw new Error("connector_scope_required");
    if(message.action === "lease.store")return connectorSession.save(b,message.command);
    if(message.action === "lease.restore")return connectorSession.read(b);
    if(message.action === "completion.ack")return connectorSession.ack(b,message.command?.operation_id);
    if(message.action === "stop")return stop("sharing_stopped",b.sharingId);
    if(message.action === "cancel") {
      if(busy?.id === message.command?.operation_id)busy.cancelled=true;
      return {cancelled:true};
    }
    if(message.action === "status") {
      const tab=await scope(b);return {status:"shared",url:sharedUrl(tab.url,b),title:tab.title,companion_version:chrome.runtime.getManifest().version,auto_connect:b.autoConnect === true,sharing_id:b.sharingId,agent_tab_id:b.agentTabId,access_mode:b.accessMode,website_scope:b.websiteScope,allowed_platforms:b.allowedPlatforms || [],active_operation:busy?.id || null,lease_recovery:true};
    }
    if(message.action === "execute")return execute(b,message.command);
    throw new Error("bridge_action_unavailable");
  })().then(reply).catch(error=>reply({error:error.message}));return true;
});
chrome.tabs.onRemoved.addListener(async id=>{await agentTabs.forget(id);const b=await binding();if(b && [b.tabId,b.connectorTabId].includes(id))await stop("shared_tab_closed",b.sharingId);});
chrome.tabs.onUpdated.addListener(async (id,change,tab)=>{
  const b=await binding();if(!b)return;
  if(id===b.tabId && change.url) {try{sharedUrl(change.url,b);}catch{await stop("tab_left_platform_scope",b.sharingId);}}
  if(id===b.connectorTabId && change.url && !sameConnector(tab,b))await stop("connector_left_browser",b.sharingId);
  if(id===b.connectorTabId && change.status === "complete" && sameConnector(tab,b))await chrome.scripting.executeScript({target:{tabId:id,frameIds:[0]},files:["shell-bridge.js"]}).catch(()=>{});
});
chrome.alarms.onAlarm.addListener(async alarm=>{
  if(alarm.name !== "connector-wake")return;
  const b=await binding();if(!b){await chrome.alarms.clear(alarm.name);return;}
  try {
    const connector=await chrome.tabs.get(b.connectorTabId);
    if(!sameConnector(connector,b))return stop("connector_left_browser",b.sharingId);
    const result=await attach(b);
    if(result.status === "attached")await chrome.tabs.sendMessage(b.connectorTabId,{target:"connector",action:"wake"},{documentId:result.binding.connectorDocumentId});
  } catch(error) {
    if(["connector_principal_changed","sharing_revoked"].includes(error.message))return stop(error.message,b.sharingId);
    // App-frame authorization/reloads briefly remove the document. Retry the
    // still-bound shell rather than discard explicit sharing on a transient race.
    const current=await chrome.tabs.get(b.connectorTabId).catch(()=>null);
    if(!current || !sameConnector(current,b))await stop("connector_unavailable",b.sharingId);
  }
});
// Alarm persistence is not assumed across worker suspension or extension reload.
void binding().then(async b=>{if(b && !await chrome.alarms.get("connector-wake"))await chrome.alarms.create("connector-wake",{periodInMinutes:0.5});});
