import "./style.css";
import {request} from "./api.js";
import {createConnector} from "./connector.js";

const connectorMode=new URLSearchParams(location.search).get("connector") === "1";
document.querySelector("#app").innerHTML=`<main><header><img src="${new URL("../public/icon.svg",import.meta.url).href}" alt="" width="36" height="36"><div><h1>Browser</h1><p>Shared Chrome connections</p></div><span class="badge">Read only</span></header>
<section class="panel"><h2>${connectorMode ? "Connect your shared tab" : "Connect Chrome to Maverick"}</h2><p>Browser manages the tab you explicitly share. Open <a id="connectors-link" href="/app/platform-connectors" target="_top">Connectors</a> to research Instagram and other platforms, read posts and inspect video.</p>
<ol><li>Download and extract <a id="download" download="maverick-browser-companion.zip">Browser Companion</a>. In <code>chrome://extensions</code> enable “Developer mode” and choose “Load unpacked”. Reload the extension after installing an updated version.</li>
<li>Copy the connector address below. Open a supported platform page in Chrome, then open the extension and share that tab.</li><li>In the Browser window opened by the extension, press “Connect”. Keep this window open while Connectors observes your source.</li></ol>
<div class="copy"><input id="url" readonly aria-label="Connector address"><button id="copy">Copy address</button></div>
<div class="actions"><button id="connect">Connect</button><button id="stop" class="secondary" hidden>Stop sharing</button></div><p id="status" class="status" role="status">${connectorMode ? "Ready to connect the tab selected in the extension." : "Your shared tabs will appear here."}</p></section>
<section class="panel"><div class="section-title"><h2>Tabs and operations</h2><button id="refresh" class="secondary">Refresh</button></div><div id="connections"></div><div id="operations"></div></section>
<footer>Sign-in and verification happen in your tab. Sharing ends when you close it, leave approved pages or stop sharing. Each sharing lease stays on the platform you selected.</footer></main>`;
const $=s=>document.querySelector(s);
let platformOrigin=location.origin;
try {const supplied=window.__MAVERICK_PLATFORM_ORIGIN__;const origin=new URL(supplied);if(["http:","https:"].includes(origin.protocol) && origin.origin===supplied)platformOrigin=origin.origin;}catch{/* Standalone Browser window. */}
$("#connectors-link").href=new URL("/app/platform-connectors",platformOrigin).href;
const url=new URL("/apps/browser/",platformOrigin);url.search="?connector=1";url.hash="";$("#url").value=url.href;
// import.meta.url belongs to the public platform mount even in an isolated app frame.
$("#download").href=new URL(/* @vite-ignore */ "../maverick-browser-companion.zip",import.meta.url).href;
$("#copy").onclick=async()=>{try{await navigator.clipboard.writeText(url.href);$("#status").textContent="Address copied.";}catch{$("#url").select();$("#status").textContent="Select and copy the address.";}};
const connector=createConnector(text=>{$("#status").textContent=text;});
$("#connect").hidden=!connectorMode;
$("#connect").onclick=async()=>{
  $("#connect").disabled=true;
  try{await connector.start();$("#stop").hidden=false;$("#connect").hidden=true;await refresh();}
  catch(error){$("#status").textContent=error.message;$("#connect").disabled=false;}
};
$("#stop").onclick=async()=>{await connector.stop();$("#stop").hidden=true;$("#connect").hidden=false;$("#connect").disabled=false;await refresh();};
function row(text,detail,action) {
  const div=document.createElement("div");div.className="row";
  const content=document.createElement("div"),strong=document.createElement("strong"),small=document.createElement("small");strong.textContent=text;small.textContent=detail;content.append(strong,small);div.append(content);
  if(action){const button=document.createElement("button");button.className="secondary";button.textContent=action.label;button.onclick=action.run;div.append(button);}return div;
}
async function refresh() {
  try {
    const overview=await request({action:"companion.overview"});$("#connections").replaceChildren();$("#operations").replaceChildren();
    if(!overview.connections.length)$("#connections").append(row("No shared tabs","Connect Chrome using the steps above."));
    for(const c of overview.connections)$("#connections").append(row(`${c.display_name} · ${c.status}`,`${c.url || "Waiting for Chrome"} · ${c.session_id}`,["connecting","connected","offline"].includes(c.status) ? {label:"Revoke",run:async()=>{await request({action:"companion.disconnect",session_id:c.session_id});await refresh();}} : null));
    for(const op of overview.operations)$("#operations").append(row(`${op.action} · ${op.status}`,`${op.operation_id} · ${new Date(op.created_at*1000).toLocaleString()}`,["queued","running","processing_media"].includes(op.status) ? {label:"Cancel",run:async()=>{await request({action:"operation.cancel",operation_id:op.operation_id});await refresh();}} : {label:"Result",run:async()=>{const result=await request({action:"operation.get",operation_id:op.operation_id});showResult(result);}}));
  } catch(error){$("#status").textContent=error.message;}
}
function showResult(result) {
  document.querySelector("dialog")?.remove();const dialog=document.createElement("dialog");const close=document.createElement("button");close.textContent="Close";close.onclick=()=>dialog.close();const pre=document.createElement("pre");
  pre.textContent=JSON.stringify(result,(key,value)=>key === "base64" ? "[captured media]" : value,2);dialog.append(close,pre);document.body.append(dialog);dialog.showModal();
}
$("#refresh").onclick=refresh;void refresh();
setInterval(()=>{if(document.visibilityState !== "hidden")void refresh();},10000);
