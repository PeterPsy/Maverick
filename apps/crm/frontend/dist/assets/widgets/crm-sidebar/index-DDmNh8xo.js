import{a as c,c as s,j as a,H as d,r}from"../../handshake-C9horJz2.js";/**
 * @license lucide-react v1.16.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const l=[["path",{d:"M3 3v16a2 2 0 0 0 2 2h16",key:"c24i48"}],["path",{d:"M18 17V9",key:"2bz60n"}],["path",{d:"M13 17V5",key:"1frdt8"}],["path",{d:"M8 17v-3",key:"17ska0"}]],p=c("chart-column",l);/**
 * @license lucide-react v1.16.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const w=[["rect",{width:"18",height:"18",x:"3",y:"3",rx:"2",key:"afitv7"}],["path",{d:"M21 9H3",key:"1338ky"}],["path",{d:"M21 15H3",key:"9uk58r"}]],h=c("rows-3",w),u=[{label:"Records",page:"records",icon:h},{label:"Pipeline",page:"pipeline",icon:d},{label:"Reports",page:"reports",icon:p}],o="(max-width: 979px)";function m(){if(typeof window>"u")return!1;try{const e=window.parent&&window.parent!==window?window.parent:window;return typeof e.matchMedia=="function"&&e.matchMedia(o).matches}catch{return typeof window.matchMedia=="function"&&window.matchMedia(o).matches}}function y(){const[e,n]=r.useState(m);return r.useEffect(()=>{if(typeof window>"u"||typeof window.matchMedia!="function")return;let t;try{t=(window.parent&&window.parent!==window?window.parent:window).matchMedia(o)}catch{t=window.matchMedia(o)}const i=()=>n(t.matches);return i(),t.addEventListener("change",i),()=>t.removeEventListener("change",i)},[]),e}function f(e=""){var n;(n=window.parent)==null||n.postMessage({type:"maverick.widget.open-app",app_id:"crm",params:e?{app_page:e}:{}},window.location.origin)}function M(){const e=y();return a.jsx("main",{className:`crm-sidebar-widget ${e?"is-shell-mobile":""}`,children:a.jsx("div",{className:"crm-sidebar-list",children:a.jsx("nav",{children:u.map(n=>{const t=n.icon;return a.jsxs("button",{className:"crm-sidebar-row",onClick:()=>f(n.page),children:[a.jsx(t,{size:15,"aria-hidden":"true"}),a.jsx("span",{children:n.label})]},n.label)})})})})}s.createRoot(document.getElementById("crm-sidebar-root")).render(a.jsx(M,{}));
