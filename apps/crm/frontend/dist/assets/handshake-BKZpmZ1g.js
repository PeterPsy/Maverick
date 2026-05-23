import{a as n}from"./createLucideIcon-B3321mH5.js";async function p(t){const a=await fetch("/api/apps/crm/backend",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(t)}),e=await a.json().catch(()=>({}));if(!a.ok){const s=typeof e.message=="string"?e.message:`Backend request failed with ${a.status}`;throw new Error(s)}return e}/**
 * @license lucide-react v1.16.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const o=[["path",{d:"m11 17 2 2a1 1 0 1 0 3-3",key:"efffak"}],["path",{d:"m14 14 2.5 2.5a1 1 0 1 0 3-3l-3.88-3.88a3 3 0 0 0-4.24 0l-.88.88a1 1 0 1 1-3-3l2.81-2.81a5.79 5.79 0 0 1 7.06-.87l.47.28a2 2 0 0 0 1.42.25L21 4",key:"9pr0kb"}],["path",{d:"m21 3 1 11h-2",key:"1tisrp"}],["path",{d:"M3 3 2 14l6.5 6.5a1 1 0 1 0 3-3",key:"1uvwmv"}],["path",{d:"M3 4h8",key:"1ep09j"}]],r=n("handshake",o);export{r as H,p as c};
