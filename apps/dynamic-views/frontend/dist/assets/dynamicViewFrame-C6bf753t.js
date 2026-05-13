import{r as n,j as h}from"./api-BDRlpRKE.js";const u=260,s=420,v=960,f="maverick.dynamic_view.resize",g=`
html, body {
  margin: 0;
  padding: 0;
  max-width: 100%;
  overflow-x: hidden;
}
* { box-sizing: border-box; }
body {
  overflow-wrap: anywhere;
  word-break: break-word;
}
img, svg, canvas, video {
  display: block;
  max-width: 100% !important;
  height: auto !important;
}
table {
  display: block;
  width: 100% !important;
  max-width: 100%;
  overflow-x: auto;
}
pre, code {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
`;function p(e){return Number.isFinite(e)?Math.min(v,Math.max(u,Math.round(e))):s}function b(e,o){const i=JSON.stringify({data:e.data||{},dataBindings:e.dataBindings||[],metadata:{id:e.id,title:e.title,summary:e.summary||"",snapshotMode:e.snapshotMode,frameId:o}},null,2);return["<!doctype html>","<html><head><meta charset='utf-8' />","<meta name='viewport' content='width=device-width, initial-scale=1' />",`<style>${g}${e.package.css||""}</style>`,"</head><body>",e.package.html,"<script>",`window.MaverickDynamicView = ${i};`,"const maverickFrameId = window.MaverickDynamicView?.metadata?.frameId || '';","function reportMaverickDynamicViewHeight() {","  const doc = document.documentElement;","  const body = document.body;","  const height = Math.max(doc?.scrollHeight || 0, doc?.offsetHeight || 0, body?.scrollHeight || 0, body?.offsetHeight || 0);","  window.parent?.postMessage({ type: 'maverick.dynamic_view.resize', frameId: maverickFrameId, height }, '*');","}","window.addEventListener('error', function(event) {","  document.body.setAttribute('data-maverick-error', String(event.message || 'runtime-error'));","  reportMaverickDynamicViewHeight();","});","window.addEventListener('load', reportMaverickDynamicViewHeight);","window.addEventListener('resize', reportMaverickDynamicViewHeight);","if (typeof ResizeObserver !== 'undefined') {","  const observer = new ResizeObserver(reportMaverickDynamicViewHeight);","  if (document.documentElement) observer.observe(document.documentElement);","  if (document.body) observer.observe(document.body);","}","<\/script>",`<script>${e.package.javascript||""}<\/script>`,"<script>reportMaverickDynamicViewHeight(); setTimeout(reportMaverickDynamicViewHeight, 32); setTimeout(reportMaverickDynamicViewHeight, 180);<\/script>","</body></html>"].join("")}function l({payload:e,title:o}){const i=n.useRef(null),[d,m]=n.useState(s),r=e.id||e.instanceId||"dynamic-view",w=n.useMemo(()=>b(e,r),[r,e]);return n.useEffect(()=>{function a(c){if(c.source!==i.current?.contentWindow)return;const t=c.data;!t||typeof t!="object"||t.type===f&&t.frameId===r&&m(p(Number(t.height)))}return window.addEventListener("message",a),()=>window.removeEventListener("message",a)},[r]),h.jsx("iframe",{ref:i,className:"dynamic-view-frame",sandbox:"allow-scripts",srcDoc:w,style:{height:d},title:o||e.title})}export{l as D};
