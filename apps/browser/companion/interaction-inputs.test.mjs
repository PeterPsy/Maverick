import test from "node:test";
import assert from "node:assert/strict";
import {boundedCommand,sharedTabUrl} from "./scope.mjs";
import {keyInput} from "./interaction-inputs.mjs";
import {websiteUrl} from "./website-scope.mjs";

const ref="c-5394d8de-023e-4e63-acf3-cdc9d56e2aee-0";
const binding={accessMode:"interactive",websiteScope:"https"};
test("interactive commands require the connection capability and snapshot refs",()=>{
  const command={operation_id:"operation",action:"type",parameters:{ref,text:"Update"}};
  assert.equal(boundedCommand(command,binding),command);
  assert.throws(()=>boundedCommand(command,{...binding,accessMode:"read_only"}),/interactive_connection_required/u);
  for(const parameters of [{ref:"#input",text:"Hi"},{ref,text:"x".repeat(20001)},{ref,text:"Hi",script:"document.cookie"}])assert.throws(()=>boundedCommand({...command,parameters},binding));
  assert.throws(()=>keyInput("Control+V"),/invalid_key/u);
  assert.equal(keyInput("Shift+Tab").modifiers,8);
  assert.equal(keyInput("Enter").text,"\r");
});
test("HTTPS agent scope preserves application routes and rejects browser/local schemes",()=>{
  const value="https://EXAMPLE.com:443/settings?section=profile#edit";
  assert.equal(websiteUrl(value),"https://example.com/settings?section=profile#edit");
  assert.equal(sharedTabUrl(value,binding,"chrome-extension://fixture/agent-tab.html"),websiteUrl(value));
  for(const url of ["http://example.com/","chrome://settings/","file:///etc/passwd","https://localhost/","https://127.0.0.1/","https://2130706433/","https://user:pass@example.com/"])assert.throws(()=>websiteUrl(url));
  assert.equal(boundedCommand({operation_id:"op",action:"navigate",parameters:{url:value}},binding).action,"navigate");
});
