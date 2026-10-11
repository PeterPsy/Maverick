import test from "node:test";
import assert from "node:assert/strict";
import {createAutoConnect} from "../frontend/src/auto-connect.js";

test("automatic setup requires the bound extension's explicit sharing generation and starts once", async () => {
  let starts = 0;
  const connect = createAutoConnect(async () => {starts++;});
  for (const status of [{}, {auto_connect:true}, {auto_connect:false,sharing_id:"selected"}]) await connect(status);
  assert.equal(starts, 0);
  await Promise.all([connect({auto_connect:true,sharing_id:"selected"}),connect({auto_connect:true,sharing_id:"selected"})]);
  assert.equal(starts, 1);
  await connect({auto_connect:true,sharing_id:"new-explicit-share"});
  assert.equal(starts, 2);
});

test("a failed automatic connection leaves manual retry available without a retry loop", async () => {
  let starts = 0;
  const connect = createAutoConnect(async () => {starts++; throw new Error("sign in");});
  await assert.rejects(connect({auto_connect:true,sharing_id:"selected"}), /sign in/u);
  await connect({auto_connect:true,sharing_id:"selected"});
  assert.equal(starts, 1);
});
