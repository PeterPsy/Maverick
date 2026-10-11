import test from "node:test";
import assert from "node:assert/strict";
import {shareableTab, setupError} from "./setup.mjs";

test("sharing starts from a supported selected tab, with actionable errors for restricted Chrome pages", () => {
  assert.equal(shareableTab({id: 10, url: "https://www.instagram.com/fixture/", title: "Fixture profile"}).id, 10);
  for (const tab of [{id: 10}, {id: 10, url: "chrome://extensions/"}, {id: 10, url: "https://maverick.test/app/browser"}]) {
    let failure; try {shareableTab(tab);} catch (error) {failure=error;}
    assert(failure); assert.match(setupError(failure), /click this extension on that tab/u);
    assert(!setupError(failure).includes("invalid_platform_url"));
  }
  assert.throws(() => shareableTab({id:10,url:"https://www.instagram.com/direct/"}), /platform_route_unavailable/u);
  assert.match(setupError(new Error("platform_route_unavailable")), /messages and settings/u);
  assert.match(setupError(new Error("browser_connector_url_required")), /Copy the connector address/u);
  assert.match(setupError(new Error("permission_denied")), /Allow access/u);
});
