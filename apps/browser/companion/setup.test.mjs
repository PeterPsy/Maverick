import test from "node:test";
import assert from "node:assert/strict";
import {selectedAgentTab, setupError, defaultConnectorUrl} from "./setup.mjs";
import {connectorUrl} from "./scope.mjs";

test("only an agent tab is connectable; ordinary platform and Chrome pages direct users to Open agent tab", () => {
  const agentUrl="chrome-extension://fixture/agent-tab.html";
  for (const tab of [{id: 10}, {id: 10, url: "chrome://extensions/"}, {id: 10, url: "https://loopino.test/app/browser"}, {id:10,url:"https://www.instagram.com/fixture/"}]) {
    let failure; try {selectedAgentTab(tab,agentUrl);} catch (error) {failure=error;}
    assert(failure); assert.match(setupError(failure), /Open agent tab/u);
    assert(!setupError(failure).includes("invalid_platform_url"));
  }
  assert.match(setupError(new Error("platform_route_unavailable")), /messages and settings/u);
  assert.match(setupError(new Error("browser_connector_url_required")), /Connection settings/u);
  assert.equal(connectorUrl(defaultConnectorUrl).origin, "https://loopino.giuntitrail.com");
  assert.match(setupError(new Error("permission_denied")), /Allow HTTPS website access/u);
});

test("only the exact Companion agent page can start an empty multi-platform tab",()=>{
  const url="chrome-extension://fixture/agent-tab.html";
  const tab=selectedAgentTab({id:10,url},url);
  assert.equal(tab.url,""); assert.equal(tab.allowed_platforms.length,6);
  for(const value of ["chrome://newtab/",url+"?spoof=1",url.replace("fixture","other")])assert.throws(()=>selectedAgentTab({id:10,url:value},url));
});

test("reconnect keeps the existing agent tab while unrelated platform tabs cannot opt in",()=>{
  const agentUrl="chrome-extension://fixture/agent-tab.html";
  const binding={tabId:10,allowedPlatforms:["instagram","youtube"]};
  const tab={id:10,url:"https://www.instagram.com/",title:"Instagram"};
  assert.equal(selectedAgentTab(tab,agentUrl,binding).reconnect,true);
  assert.throws(()=>selectedAgentTab({...tab,id:11},agentUrl,binding),/agent_tab_required/u);
  assert.throws(()=>selectedAgentTab(tab,agentUrl,{...binding,allowedPlatforms:[]}),/agent_tab_required/u);
  assert.throws(()=>selectedAgentTab({...tab,url:"https://x.com/home/"},agentUrl,binding),/shared_platform_scope_required/u);
});
