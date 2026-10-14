import assert from "node:assert/strict";

const html=`<!doctype html><html><head><title>Owned interactive fixture</title></head><body>
<form id="form"><label>Name <input id="name" value="Original"></label>
<label>Preference <select id="preference"><option value="old">Old</option><option value="new">New</option></select></label>
<label><input type="checkbox" id="enabled">Enabled</label><button>Save</button></form>
<label>Private password <input type="password" value="never-expose-this-value"></label>
<input hidden aria-label="Hidden input" value="hidden-value"><button id="hover">Hover action</button>
<div id="shadow"></div><iframe title="Embedded form" srcdoc='<label>Frame note <input></label>'></iframe>
<a href="/next?from=form#content" target="_blank">Next page</a><p id="status">Waiting</p><script>
window.events=[];window.saved=[];
document.addEventListener('input',e=>window.events.push({type:e.type,trusted:e.isTrusted}));
document.addEventListener('keydown',e=>window.events.push({type:e.type,trusted:e.isTrusted,key:e.key}));
document.addEventListener('click',e=>window.events.push({type:e.type,trusted:e.isTrusted}));
document.querySelector('#hover').onmouseenter=e=>window.hoverTrusted=e.isTrusted;
document.querySelector('#form').onsubmit=e=>{e.preventDefault();window.saved.push({name:document.querySelector('#name').value,preference:document.querySelector('#preference').value,enabled:document.querySelector('#enabled').checked});document.querySelector('#status').textContent='Saved';};
document.querySelector('#shadow').attachShadow({mode:'open'}).innerHTML='<label>Shadow note <input></label>';
</script></body></html>`;

export async function verifyInteractiveChrome({context,worker,page,connection,run,runMcp,api,reloadBridge}) {
  const url="https://owned-browser.example/settings?section=profile#edit";
  await context.route("https://owned-browser.example/**",route=>route.fulfill({contentType:"text/html",body:html}));
  await run("navigate",{url},connection);
  assert.equal(page.url(),url);
  const snapshot=await runMcp("browser_snapshot",{});
  assert(snapshot.elements.length>=8);
  assert(!JSON.stringify(snapshot).includes("never-expose-this-value"));
  assert(!snapshot.elements.some(e=>e.name === "Hidden input"));
  const ref=name=>{const e=snapshot.elements.find(e=>e.name === name);assert(e,`Missing control ${name}`);return e.ref;};
  await runMcp("browser_type",{ref:ref("Name"),text:"Updated from agent"});
  assert.equal(await page.locator("#name").inputValue(),"Updated from agent");
  await runMcp("browser_select_option",{ref:ref("Preference"),values:["new"]});
  await runMcp("browser_set_checked",{ref:ref("Enabled"),checked:true});
  await runMcp("browser_hover",{ref:ref("Hover action")});
  assert.equal(await page.evaluate(()=>window.hoverTrusted),true);
  await runMcp("browser_type",{ref:ref("Shadow note"),text:"Shadow edited"});
  assert.equal(await page.locator("#shadow input").inputValue(),"Shadow edited");
  await runMcp("browser_type",{ref:ref("Frame note"),text:"Frame edited"});
  assert.equal(await page.frameLocator("iframe").locator("input").inputValue(),"Frame edited");
  await runMcp("browser_press_key",{ref:ref("Name"),key:"Enter"});
  assert.deepEqual(await page.evaluate(()=>window.saved),[{name:"Updated from agent",preference:"new",enabled:true}]);
  await runMcp("browser_click",{ref:ref("Save")});
  assert.equal(await page.evaluate(()=>window.saved.length),2);
  // Lose the old page's completion response after the click actually happened.
  // Reload resumes the retained result, rather than clicking Save a fourth time.
  let recoveryOperation,suppressed=false;
  const intercept=async route=>{
    const body=route.request().postDataJSON();
    if(body?.action === "companion.complete" && body.operation_id === recoveryOperation && !suppressed){suppressed=true;await route.abort();}
    else await route.continue();
  };
  const completionRoute="**/.well-known/loopino-app-background/request";
  await context.route(completionRoute,intercept);
  const queued=await api({action:"click",session_id:connection.session_id,ref:ref("Save")});recoveryOperation=queued.operation_id;
  for(let i=0;i<300 && !suppressed;i++)await new Promise(resolve=>setTimeout(resolve,100));
  assert(suppressed,"The completed click's response must be interrupted");
  await reloadBridge();
  let recovered;
  for(let i=0;i<300;i++){
    recovered=await api({action:"operation.get",operation_id:recoveryOperation});
    if(recovered.status === "completed")break;
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  assert.equal(recovered.status,"completed",JSON.stringify(recovered));
  assert.equal(await page.evaluate(()=>window.saved.length),3,"Reload must not replay a completed form submission");
  await context.unroute(completionRoute,intercept);
  const events=await page.evaluate(()=>window.events);
  assert(events.some(e=>e.type === "input" && e.trusted));
  assert(events.some(e=>e.type === "keydown" && e.key === "Enter" && e.trusted));
  assert(events.some(e=>e.type === "click" && e.trusted));
  const stillAttached=await worker.evaluate(async()=>{const {binding}=await chrome.storage.session.get('binding');try {await chrome.debugger.sendCommand({tabId:binding.tabId},'Page.getLayoutMetrics');return true;}catch{return false;}});
  assert.equal(stillAttached,false,"Debugger attachment is released after each action");
  // A same-looking replacement node must not inherit authority from the old ref.
  await page.locator("#name").evaluate(e=>{const replacement=e.cloneNode();e.replaceWith(replacement);});
  const stale=await runMcp("browser_type",{ref:ref("Name"),text:"Must not change"},"failed");
  assert.match(stale.detail,/snapshot_ref_stale/u);
  assert.equal(await page.locator("#name").inputValue(),"Updated from agent");
  // Actions never target another user's open tab.
  const other=await context.newPage();await other.goto(url);await other.bringToFront();
  const refreshed=await runMcp("browser_snapshot",{});
  const nameRef=refreshed.elements.find(e=>e.name === "Name").ref;
  await page.locator('#name').evaluate(e=>{e.disabled=true;});
  const disabled=await runMcp("browser_type",{ref:nameRef,text:"Must not edit"},"failed");
  assert.match(disabled.detail,/element_disabled/u);
  await page.locator('#name').evaluate(e=>{e.disabled=false;e.readOnly=true;});
  const readonly=await runMcp("browser_type",{ref:nameRef,text:"Must not edit"},"failed");
  assert.match(readonly.detail,/element_not_editable/u);
  await page.locator('#name').evaluate(e=>{e.readOnly=false;});
  await runMcp("browser_type",{ref:nameRef,text:"Only the agent tab"});
  assert.equal(await other.locator("#name").inputValue(),"Original");
  assert.equal(await page.locator("#name").inputValue(),"Only the agent tab");
  await other.close();
  const count=context.pages().length;
  await runMcp("browser_click",{ref:refreshed.elements.find(e=>e.name === "Next page").ref});
  await page.waitForURL("https://owned-browser.example/next?from=form#content");
  assert.equal(context.pages().length,count,"Links remain in the agent tab");
  await run("navigate",{url:"https://www.instagram.com/fixture_user/"},connection);
  const navigated=await runMcp("browser_click",{ref:ref("Save")},"failed");
  assert.match(navigated.detail,/document|snapshot_ref/u);
  console.log(JSON.stringify({phase:"interactive-chrome",trusted_click:true,trusted_input:true,trusted_keys:true,form_submission:true,select:true,checkbox:true,hover:true,shadow_dom:true,same_origin_frame:true,stale_refs_rejected:true,other_tab_unchanged:true,debugger_released:true,same_tab_link_navigation:true}));
}
