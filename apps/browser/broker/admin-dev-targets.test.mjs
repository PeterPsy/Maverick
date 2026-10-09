import assert from "node:assert/strict";
import test from "node:test";
import { isAdminDevTarget, proxyTunnelUrl } from "./admin-dev-targets.mjs";

const targets = new Set(["http://maverick.localhost:8000", "http://hostmachine:8014"]);
const frame = `af-${"a".repeat(24)}.sidecars.maverick.localhost`;
test("only exact platform hosts and Core app-frame labels inherit approved ports", () => {
  assert.equal(isAdminDevTarget(targets, "http", "maverick.localhost", 8000), true);
  assert.equal(isAdminDevTarget(targets, "http", frame, 8000), true);
  for (const host of ["other.localhost", "anything.sidecars.maverick.localhost", frame + ".evil", frame.replace("af-", "sc-"), frame.replace("maverick", "other")]) {
    assert.equal(isAdminDevTarget(targets, "http", host, 8000), false);
  }
  assert.equal(isAdminDevTarget(targets, "http", frame, 9000), false);
  assert.equal(isAdminDevTarget(targets, "https", frame, 8000), false);
});
test("CONNECT on configured HTTP dev ports supports ws without admitting other private destinations", () => {
  assert.equal(proxyTunnelUrl("hostmachine:8014", targets).href, "http://hostmachine:8014/");
  assert.equal(proxyTunnelUrl(`${frame}:8000`, targets).protocol, "http:");
  assert.equal(proxyTunnelUrl("example.com:443", targets).protocol, "https:");
  assert.equal(proxyTunnelUrl("127.0.0.1:8000", targets).protocol, "https:");
});
