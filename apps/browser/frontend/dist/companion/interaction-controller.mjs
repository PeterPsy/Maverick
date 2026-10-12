import {interactionDom} from "./interaction-dom.mjs";
import {keyInput,validateInteraction} from "./interaction-inputs.mjs";

export function createInteractionController(chrome,{scope,check,delay}) {
  const invoke=async(b,action,p,documentId)=>{
    check();await scope(b);
    const results=await chrome.scripting.executeScript({target:{tabId:b.tabId,...(documentId ? {documentIds:[documentId]} : {frameIds:[0]})},func:interactionDom,args:[action,p]});
    if(!results[0]?.result)throw new Error("interaction_unavailable");
    if(results[0].result.error)throw new Error(results[0].result.error);
    return results[0];
  };
  return {
    async snapshot(b,p) {
      const result=await invoke(b,"snapshot",{max_items:p.max_items ?? 100});
      if(!result.documentId)throw new Error("snapshot_document_unavailable");
      await chrome.storage.session.set({interactionSnapshot:{sharingId:b.sharingId,documentId:result.documentId,refs:result.result.elements.map(e=>e.ref)}});
      return result.result;
    },
    async run(b,action,p) {
      validateInteraction(action,p);
      const {interactionSnapshot:snapshot}=await chrome.storage.session.get("interactionSnapshot");
      if(snapshot?.sharingId !== b.sharingId || !snapshot.refs.includes(p.ref))throw new Error("snapshot_ref_stale");
      const target={tabId:b.tabId};let attached=false,pressed=null;
      const send=async(method,params)=>{check();await scope(b);return chrome.debugger.sendCommand(target,method,params);};
      try {
        check();await scope(b);
        try {await chrome.debugger.attach(target,"1.3");attached=true;}catch {throw new Error("browser_control_unavailable");}
        const prepared=(await invoke(b,"prepare",{...p,action},snapshot.documentId)).result;
        const click=async()=>{
          await send("Input.dispatchMouseEvent",{type:"mouseMoved",x:prepared.x,y:prepared.y});
          const latest=(await invoke(b,"prepare",{...p,action},snapshot.documentId)).result;
          if(Math.abs(latest.x-prepared.x)>1 || Math.abs(latest.y-prepared.y)>1)throw new Error("element_moving");
          await send("Input.dispatchMouseEvent",{type:"mousePressed",x:prepared.x,y:prepared.y,button:"left",clickCount:1});pressed="mouse";
          await send("Input.dispatchMouseEvent",{type:"mouseReleased",x:prepared.x,y:prepared.y,button:"left",clickCount:1});pressed=null;
        };
        let detail={};
        if(action === "click")await click();
        if(action === "hover")await send("Input.dispatchMouseEvent",{type:"mouseMoved",x:prepared.x,y:prepared.y});
        if(action === "type") {
          await click();
          await invoke(b,"focus_type",p,snapshot.documentId);
          if(p.text)await send("Input.insertText",{text:p.text});
          else {await send("Input.dispatchKeyEvent",{type:"rawKeyDown",...keyInput("Backspace")});pressed="Backspace";await send("Input.dispatchKeyEvent",{type:"keyUp",...keyInput("Backspace")});pressed=null;}
          try {detail=(await invoke(b,"typed_state",p,snapshot.documentId)).result;}catch {detail={refresh_snapshot:true};}
        }
        if(action === "press_key") {
          await invoke(b,"focus_key",p,snapshot.documentId);
          const input=keyInput(p.key);
          await send("Input.dispatchKeyEvent",{type:input.text ? "keyDown" : "rawKeyDown",...input});pressed=p.key;
          await send("Input.dispatchKeyEvent",{type:"keyUp",...input,text:undefined});pressed=null;
        }
        if(action === "set_checked") {
          if(prepared.checked !== p.checked)await click();
          try {detail=(await invoke(b,"checked",p,snapshot.documentId)).result;}catch {detail={refresh_snapshot:true};}
        }
        if(action === "select_option")detail=(await invoke(b,"select_option",p,snapshot.documentId)).result;
        await delay(250);check();await scope(b);
        return {action,ref:p.ref,performed:true,...detail};
      } finally {
        // Release only fixed input state after cancellation; never retry the action.
        if(attached && pressed) {
          const method=pressed === "mouse" ? "Input.dispatchMouseEvent" : "Input.dispatchKeyEvent";
          const params=pressed === "mouse" ? {type:"mouseReleased",x:-1,y:-1,button:"left",clickCount:1} : {type:"keyUp",...keyInput(pressed),text:undefined};
          await chrome.debugger.sendCommand(target,method,params).catch(()=>{});
        }
        if(attached)await chrome.debugger.detach(target).catch(()=>{});
      }
    },
  };
}
