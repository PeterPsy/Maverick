import test from "node:test";
import assert from "node:assert/strict";
import {connectionDetail, stopReason} from "../frontend/src/sharing-state.js";

test("stopped and offline empty agent tabs do not advertise readiness", () => {
  const tab = {sharing_mode: "agent_tab", allowed_platforms: ["instagram", "youtube"], url: ""};
  assert.match(connectionDetail({...tab, status: "connected"}), /Ready for agent navigation/u);
  for (const status of ["revoked", "offline"]) assert(!connectionDetail({...tab, status}).includes("Ready"));
  assert.match(connectionDetail({...tab, status: "revoked", stop_reason: "extension_unavailable"}), /reload the extension/u);
  assert.match(connectionDetail({...tab, status: "revoked", stop_reason: "constructor"}), /Sharing stopped/u);
  assert.equal(stopReason({code: "extension_unavailable"}), "extension_unavailable");
  assert.equal(stopReason({code: "private-detail", status: 401}), "authentication_failed");
  assert.equal(stopReason({code: "constructor"}), "heartbeat_failed");
});
