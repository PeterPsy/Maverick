import {boundedCommand,connectorUrl,instagramUrl,sameConnector} from "./scope.mjs";
import {observe} from "./dom-actions.mjs";
import {collectInstagram,analyzeVideo} from "./workflows.mjs";

let busy=null;
let lastScreenshotAt=0;
const activationGenerations=new Map();
chrome.tabs.onActivated.addListener(event=>{activationGenerations.set(event.windowId,(activationGenerations.get(event.windowId) || 0)+1);});
chrome.windows.onRemoved.addListener(id=>activationGenerations.delete(id));
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const binding=async()=> (await chrome.storage.session.get("binding")).binding;
async function capture(action,parameters={}) {
  const result=await chrome.runtime.sendMessage({target:"offscreen",action,parameters});
  if(!result || result.error)throw new Error(result?.error || "capture_unavailable");return result;
}
async function screenshot(b,parameters) {
  await scope(b);
  const tab=await chrome.tabs.update(b.tabId,{active:true});
  await delay(Math.max(100,600-(Date.now()-lastScreenshotAt)));
  await scope(b);
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
async function stop(reason="sharing_stopped") {
  if(busy)busy.cancelled=true;
  const shared=await binding();
  if(shared)await dom(shared,"video.restore",{},busy?.expected).catch(()=>{});
  await chrome.storage.session.remove("binding");
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
  instagramUrl(tab.url);
  return tab;
}
async function dom(b,action,parameters={},expected) {
  const tab=await scope(b);
  if(expected && instagramUrl(tab.url) !== expected.url)throw new Error("shared_tab_changed_during_operation");
  const target={tabId:b.tabId,...(expected?.documentId ? {documentIds:[expected.documentId]} : {})};
  const loaded=await chrome.scripting.executeScript({target,files:["reader.js"]});
  if(expected && !expected.documentId)expected.documentId=loaded[0]?.documentId;
  const results=await chrome.scripting.executeScript({target:{tabId:b.tabId,...(expected?.documentId ? {documentIds:[expected.documentId]} : {})},func:observe,args:[action,parameters]});
  const after=await scope(b);
  if(expected && instagramUrl(after.url) !== expected.url)throw new Error("shared_tab_changed_during_operation");
  if(results[0]?.result == null)throw new Error("observation_unavailable");
  if(results[0].result.error)throw new Error(results[0].result.detail || results[0].result.error);
  return results[0].result;
}
async function navigate(b,url) {
  await scope(b);await chrome.tabs.update(b.tabId,{url:instagramUrl(url)});
  const end=Date.now()+15000;
  while(Date.now()<end) {
    const tab=await scope(b);
    if(tab.status === "complete" && instagramUrl(tab.url) === instagramUrl(url)) {
      await delay(1000);return {url:instagramUrl(tab.url),title:tab.title};
    }
    await delay(100);
  }
  throw new Error("navigation_timeout");
}
async function execute(b,command) {
  boundedCommand(command);
  const initial=await scope(b);
  if(busy)throw new Error("operation_already_running");
  const task={id:command.operation_id,cancelled:false};busy=task;
  const expected={url:instagramUrl(initial.url),documentId:null};
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
    navigate:async url=>{check();const result=await navigate(b,url);expected.url=instagramUrl(url);expected.documentId=null;return result;},
    capture:async(a,p)=>{check();await fixedDom("wait_for",{});const result=a === "frame" ? await screenshot(b,p) : await capture(a,p);await fixedDom("wait_for",{});return result;},
    cleanup:async(a,p)=>{await scope(b);return a === "video.restore" ? dom(b,a,p,expected) : capture(a,p);}};
  try {
    check();const p=command.parameters || {};let result;
    if(command.action === "navigate")result=await adapter.navigate(p.url);
    else if(command.action === "instagram.collect")result=await collectInstagram(adapter,p);
    else if(command.action === "video.analyze")result=await analyzeVideo(adapter,p);
    else if(command.action === "screenshot")result=await adapter.capture("frame",{});
    else if(command.action === "video.frame") {
      try{const timing=await adapter.dom("video.prepare",p);result={...await adapter.capture("frame",timing),time_seconds:timing.presented_time_seconds,requested_time_seconds:p.time_seconds ?? null,video_index:p.video_index ?? 0};}
      finally{await dom(b,"video.restore",p,expected).catch(()=>{});}
    } else if(command.action === "tabs") {const tab=await scope(b);result={tabs:[{url:instagramUrl(tab.url),title:tab.title,shared:true}]};}
    else result=await adapter.dom(command.action,p);
    check();const tab=await scope(b);
    return {...result,source_url:instagramUrl(tab.url),observed_at:new Date().toISOString()};
  } finally {if(busy===task)busy=null;}
}
async function share(message) {
  const url=connectorUrl(message.url);const tab=await chrome.tabs.get(message.tabId);instagramUrl(tab.url);
  await stop();
  try {
    await chrome.offscreen.createDocument({url:"offscreen.html",reasons:["USER_MEDIA"],justification:"Read-only capture of the single Instagram tab explicitly shared by the user."});
    // Chrome 116+ permits worker-issued stream IDs in the offscreen document.
    const streamId=await chrome.tabCapture.getMediaStreamId({targetTabId:tab.id});
    await capture("start",{streamId});
    const window=await chrome.windows.create({url:url.href,type:"popup",width:1040,height:850});
    const connector=window.tabs[0];
    await chrome.storage.session.set({binding:{sharingId:crypto.randomUUID(),tabId:tab.id,connectorTabId:connector.id,origin:url.origin,path:url.pathname}});
    await chrome.alarms.create("connector-wake",{periodInMinutes:0.5});
    await chrome.action.setBadgeText({text:"READ"});await chrome.action.setBadgeBackgroundColor({color:"#5665df"});
    // A tab may finish loading before onUpdated observes the stored binding.
    const loaded=await chrome.tabs.get(connector.id);
    if(loaded.status === "complete")await chrome.scripting.executeScript({target:{tabId:connector.id},files:["content.js"]});
    return {status:"shared"};
  } catch(error) {await stop();throw error;}
}
chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  if(sender.id !== chrome.runtime.id || message.target !== "worker")return;
  (async()=>{
    if(message.action === "share") {
      if(sender.url !== chrome.runtime.getURL("popup.html"))throw new Error("popup_gesture_required");
      return share(message);
    }
    if(message.action === "stop" && sender.url === chrome.runtime.getURL("popup.html"))return stop();
    const b=await binding();
    if(!b || !sender.tab || !sameConnector(sender.tab,b))throw new Error("connector_scope_required");
    if(message.action === "stop")return stop();
    if(message.action === "cancel") {
      if(busy?.id === message.command?.operation_id)busy.cancelled=true;
      return {cancelled:true};
    }
    if(message.action === "status") {
      const tab=await scope(b);return {status:"shared",url:instagramUrl(tab.url),title:tab.title,active_operation:busy?.id || null};
    }
    if(message.action === "execute")return execute(b,message.command);
    throw new Error("bridge_action_unavailable");
  })().then(reply).catch(error=>reply({error:error.message}));return true;
});
chrome.tabs.onRemoved.addListener(async id=>{const b=await binding();if(b && [b.tabId,b.connectorTabId].includes(id))await stop("shared_tab_closed");});
chrome.tabs.onUpdated.addListener(async (id,change,tab)=>{
  const b=await binding();if(!b)return;
  if(id===b.tabId && change.url) {try{instagramUrl(change.url);}catch{await stop("tab_left_instagram_scope");}}
  if(id===b.connectorTabId && change.url && !sameConnector(tab,b))await stop("connector_left_browser");
  if(id===b.connectorTabId && change.status === "complete" && sameConnector(tab,b))await chrome.scripting.executeScript({target:{tabId:id},files:["content.js"]}).catch(()=>stop("connector_injection_failed"));
});
chrome.alarms.onAlarm.addListener(async alarm=>{
  if(alarm.name !== "connector-wake")return;
  const b=await binding();if(!b){await chrome.alarms.clear(alarm.name);return;}
  try {
    const connector=await chrome.tabs.get(b.connectorTabId);
    if(!sameConnector(connector,b))return stop("connector_left_browser");
    await chrome.tabs.sendMessage(b.connectorTabId,{target:"connector",action:"wake"});
  } catch {await stop("connector_unavailable");}
});
// Alarm persistence is not assumed across worker suspension or extension reload.
void binding().then(async b=>{if(b && !await chrome.alarms.get("connector-wake"))await chrome.alarms.create("connector-wake",{periodInMinutes:0.5});});
