import test from "node:test";
import assert from "node:assert/strict";
import {shareableTab, setupError, defaultConnectorUrl} from "./setup.mjs";
import {connectorUrl} from "./scope.mjs";

test("sharing starts from a supported selected tab, with actionable errors for restricted Chrome pages", () => {
  assert.equal(shareableTab({id: 10, url: "https://www.instagram.com/fixture/", title: "Fixture profile"}).id, 10);
  assert.equal(shareableTab({id:10,url:"https://www.instagram.com/"}).url,"https://www.instagram.com/");
  for (const tab of [{id: 10}, {id: 10, url: "chrome://extensions/"}, {id: 10, url: "https://maverick.test/app/browser"}]) {
    let failure; try {shareableTab(tab);} catch (error) {failure=error;}
    assert(failure); assert.match(setupError(failure), /click this extension on that tab/u);
    assert(!setupError(failure).includes("invalid_platform_url"));
  }
  assert.throws(() => shareableTab({id:10,url:"https://www.instagram.com/direct/"}), /platform_route_unavailable/u);
  assert.match(setupError(new Error("platform_route_unavailable")), /messages and settings/u);
  assert.match(setupError(new Error("browser_connector_url_required")), /Connection settings/u);
  assert.equal(connectorUrl(defaultConnectorUrl).origin, "https://maverick.loopino.ai");
  assert.match(setupError(new Error("permission_denied")), /Allow access/u);
});

test("only the exact Companion agent page can start an empty multi-platform tab",()=>{
  const url="chrome-extension://fixture/agent-tab.html";
  const tab=shareableTab({id:10,url},url);
  assert.equal(tab.url,""); assert.equal(tab.allowed_platforms.length,6);
  for(const value of ["chrome://newtab/",url+"?spoof=1",url.replace("fixture","other")])assert.throws(()=>shareableTab({id:10,url:value},url));
});
