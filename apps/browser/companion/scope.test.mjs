import test from "node:test";
import assert from "node:assert/strict";
import {instagramUrl,connectorUrl,boundedCommand,sameConnector} from "./scope.mjs";
import {collectInstagram,analyzeVideo} from "./workflows.mjs";

test("Instagram scope excludes credentials, login, redirects and URL normalization tricks",()=>{
  assert.equal(instagramUrl("https://www.instagram.com/martagiunti/?token=s#anchor"),"https://www.instagram.com/martagiunti/");
  for(const url of ["https://www.instagram.com/accounts/login/","https://www.instagram.com/direct/","https://evil.test/marta/","https://secret@www.instagram.com/marta/","https://www.instagram.com/marta/../accounts/","https://www.instagram.com/%61pi/"," https://www.instagram.com/marta/","https://www.instagram.com/marta//"])assert.throws(()=>instagramUrl(url),undefined,url);
});
test("Connector is restricted to the selected secure Browser window",()=>{
  const url=connectorUrl("https://frame.maverick.test/apps/browser/?connector=1");
  const b={connectorTabId:10,origin:url.origin,path:url.pathname};
  assert(sameConnector({id:10,url:url.href},b));assert(!sameConnector({id:11,url:url.href},b));assert(!sameConnector({id:10,url:"https://evil.test/apps/browser/?connector=1"},b));
  for(const url of ["https://maverick.test/apps/chat/","http://maverick.test/apps/browser/","https://user:pass@maverick.test/apps/browser/"])assert.throws(()=>connectorUrl(url));
});
test("Fixed command surface rejects scripts, selectors and excessive media duration",()=>{
  for(const command of [{action:"click",parameters:{}},{action:"content.read",parameters:{script:"document.cookie"}},{action:"scroll",parameters:{selector:"body"}},{action:"video.analyze",parameters:{max_seconds:181}},{action:"screenshot",parameters:{full_page:true}}])assert.throws(()=>boundedCommand({operation_id:"one",...command}));
});
test("Collection deduplicates links across scrolling and reports item limit",async()=>{
  let read=0;
  const adapter={check(){},async navigate(){},async scroll(){return {at_bottom:false,moved:true};},async read(){read++;return {url:"https://www.instagram.com/marta/",text:"Marta",links:[{url:"https://www.instagram.com/p/a/?tracking=1",text:"first"},{url:`https://www.instagram.com/reel/${read}/`,text:"reel"}],observed_at:"now"};}};
  const result=await collectInstagram(adapter,{username:"marta",max_items:3,max_batches:10});
  assert.equal(result.items.length,3);assert.equal(result.stop_reason,"item_limit");assert.equal(result.items[0].url,"https://www.instagram.com/p/a/");assert.equal(result.batches.length,2);
});
test("Collection stops at rendered end or a login gate without claiming a complete feed",async()=>{
  const adapter={check(){},async navigate(){},async scroll(){return {at_bottom:true,moved:false};},async read(){return {url:"https://www.instagram.com/marta/",text:"Marta",links:[],observed_at:"now"};}};
  assert.equal((await collectInstagram(adapter,{username:"marta",include_reels:false})).stop_reason,"rendered_end");
  adapter.read=async()=>({url:"https://www.instagram.com/accounts/login/",text:"",links:[]});
  assert.equal((await collectInstagram(adapter,{username:"marta"})).stop_reason,"login_required");
});
test("Video analysis samples bounded times and restores playback after failure",async()=>{
  const calls=[];
  const adapter={check(){},async dom(a,p){calls.push([a,p]);return {duration_seconds:30,current_time_seconds:p.time_seconds};},async capture(){return {base64:"jpeg"};}};
  const result=await analyzeVideo(adapter,{frame_count:3,max_seconds:10,include_audio:false});
  assert.equal(result.frames.length,3);assert(result.truncated);assert(result.frames.every(f=>f.time_seconds<10));assert.equal(calls.at(-1)[0],"video.restore");
  adapter.capture=async()=>{throw new Error("capture_failed");};
  await assert.rejects(analyzeVideo(adapter,{include_audio:false}),/capture_failed/u);assert.equal(calls.at(-1)[0],"video.restore");
  adapter.dom=async(a)=>{calls.push([a]);if(a === "video.prepare")throw new Error("prepare_failed");};
  await assert.rejects(analyzeVideo(adapter,{}),/prepare_failed/u);assert.equal(calls.at(-1)[0],"video.restore");
});
