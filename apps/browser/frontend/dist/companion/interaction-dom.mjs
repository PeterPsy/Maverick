// Fixed DOM adapter serialized into the source's isolated extension world.
// References retain the actual node; a replacement node never inherits its ref.
export function interactionDom(action,p) {
  try {
    const labelText=label=>{const copy=label.cloneNode(true);copy.querySelectorAll('input,select,textarea,button,script,style').forEach(node=>node.remove());return copy.textContent;};
    const name=e=>(e.getAttribute("aria-label") || e.getAttribute("aria-labelledby")?.split(/\s+/u).map(id=>e.getRootNode().getElementById?.(id)?.textContent || "").join(" ")
      || [...(e.labels || [])].map(labelText).join(" ") || e.getAttribute("alt") || e.getAttribute("title") || e.innerText || e.getAttribute("placeholder") || "").trim().slice(0,500);
    const visible=e=>{
      const style=e.ownerDocument.defaultView.getComputedStyle(e);
      return e.isConnected && e.getClientRects().length && style.display !== "none" && style.visibility !== "hidden" && !e.closest('[inert],[aria-hidden="true"]');
    };
    const signature=e=>JSON.stringify([e.tagName,e.getAttribute("type"),name(e),e.getAttribute("href")]);
    const point=e=>{
      const rect=e.getBoundingClientRect();
      let x=rect.x+rect.width/2,y=rect.y+rect.height/2,view=e.ownerDocument.defaultView;
      while(view !== window) {
        const frame=view.frameElement;
        if(!frame)throw new Error("embedded_frame_unavailable");
        const r=frame.getBoundingClientRect(),sx=r.width/frame.offsetWidth,sy=r.height/frame.offsetHeight;
        if(!Number.isFinite(sx) || !Number.isFinite(sy))throw new Error("embedded_frame_unavailable");
        x=r.x+(x+frame.clientLeft)*sx;y=r.y+(y+frame.clientTop)*sy;
        const hit=frame.getRootNode().elementFromPoint?.(x,y) || frame.ownerDocument.elementFromPoint(x,y);
        if(hit !== frame)throw new Error("element_covered");
        view=frame.ownerDocument.defaultView;
      }
      return {x,y};
    };
    const role=e=>e.getAttribute("role") || ({A:"link",BUTTON:"button",TEXTAREA:"textbox",SELECT:"combobox",SUMMARY:"button"}[e.tagName])
      || (e.tagName === "INPUT" ? ({checkbox:"checkbox",radio:"radio",button:"button",submit:"button",range:"slider"}[e.type] || "textbox") : e.isContentEditable ? "textbox" : "control");
    if(action === "snapshot") {
      const token=crypto.randomUUID(),refs=new Map(),elements=[],seen=new Set();
      const collect=root=>{
        for(const e of root.querySelectorAll('a[href],button,input,textarea,select,summary,[role],[tabindex],[contenteditable],iframe,*')) {
          if(seen.size>=20000 || elements.length>=p.max_items)break;
          if(seen.has(e))continue;
          seen.add(e);
          if(!visible(e))continue;
          if(e.matches('a[href],button,input:not([type="hidden"]),textarea,select,summary,[role="button"],[role="link"],[role="checkbox"],[role="radio"],[role="switch"],[role="combobox"],[role="textbox"],[role="menuitem"],[role="option"],[role="tab"],[role="treeitem"],[tabindex],[contenteditable="true"]')) {
            const ref=`c-${token}-${elements.length}`,record={ref,role:role(e),name:name(e),tag:e.tagName.toLowerCase(),type:e.type || null,disabled:Boolean(e.disabled),readonly:Boolean(e.readOnly)};
            if(e.type === "checkbox" || e.type === "radio")record.checked=e.checked;
            if(e.getAttribute("aria-checked"))record.checked=e.getAttribute("aria-checked") === "true";
            if(e.tagName === "SELECT")record.options=[...e.options].slice(0,50).map(o=>({value:o.value.slice(0,1000),label:o.label.slice(0,500),selected:o.selected,disabled:o.disabled}));
            if(["INPUT","TEXTAREA"].includes(e.tagName) && !["password","file"].includes(e.type))record.value=e.value.slice(0,2000);
            refs.set(ref,{element:e,signature:signature(e)});elements.push(record);
          }
          if(e.shadowRoot)collect(e.shadowRoot);
          if(e.tagName === "IFRAME") {try {if(e.contentDocument)collect(e.contentDocument);}catch { /* Cross-origin frame remains unobserved. */ }}
        }
      };
      collect(document);
      globalThis.maverickInteractiveRefs={refs,url:location.href};
      return {elements,coverage:"Rendered controls in this page, open shadow roots and same-origin embedded frames."};
    }
    const state=globalThis.maverickInteractiveRefs,stored=state?.refs.get(p.ref),e=stored?.element;
    if(!e || state.url !== location.href || !visible(e) || stored.signature !== signature(e))throw new Error("snapshot_ref_stale");
    if(e.disabled || e.getAttribute("aria-disabled") === "true")throw new Error("element_disabled");
    if(action === "prepare") {
      if(p.action === "type" && (e.readOnly || !(e.tagName === "TEXTAREA" || e.isContentEditable || e.tagName === "INPUT" && ["text","search","email","tel","url","number"].includes(e.type))))throw new Error("element_not_editable");
      if(p.action === "click" && e.type === "file")throw new Error("file_input_requires_user");
      if(p.action === "select_option" && e.tagName !== "SELECT")throw new Error("select_element_required");
      if(p.action === "set_checked" && !["checkbox","radio","switch"].includes(role(e)))throw new Error("checkable_element_required");
      e.scrollIntoView({block:"center",inline:"center",behavior:"instant"});
      const {x,y}=point(e);
      // Hit testing occurs in the element's own document, including shadow roots.
      const r=e.getBoundingClientRect(),hit=e.getRootNode().elementFromPoint?.(r.x+r.width/2,r.y+r.height/2) || e.ownerDocument.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
      if(!hit || !(hit === e || e.contains(hit)))throw new Error("element_covered");
      if(x<0 || y<0 || x>=innerWidth || y>=innerHeight)throw new Error("element_outside_viewport");
      if(p.action === "click" && e.tagName === "A" && e.target)e.target="_self";
      if(p.action === "click" && e.form?.target)e.form.target="_self";
      const checked=["checkbox","radio"].includes(e.type) ? e.checked : e.getAttribute("aria-checked") === "true";
      if(p.action === "set_checked" && e.type === "radio" && p.checked === false && checked)throw new Error("radio_cannot_be_unchecked");
      return {x,y,checked};
    }
    if(action === "focus_type") {
      if(e.readOnly)throw new Error("element_not_editable");
      e.focus();
      if(!e.isConnected)throw new Error("snapshot_ref_stale");
      if(e.isContentEditable) {const range=e.ownerDocument.createRange();range.selectNodeContents(e);const selection=e.ownerDocument.getSelection();selection.removeAllRanges();selection.addRange(range);}
      else e.select();
      return {focused:true};
    }
    if(action === "focus_key") {e.focus();if(e.getRootNode().activeElement !== e)throw new Error("element_cannot_receive_keys");return {focused:true};}
    if(action === "checked")return {checked:["checkbox","radio"].includes(e.type) ? e.checked : e.getAttribute("aria-checked") === "true"};
    if(action === "typed_state")return {text_length:(e.isContentEditable ? e.innerText : e.value).length,matches_requested_text:(e.isContentEditable ? e.innerText : e.value) === p.text};
    if(action === "select_option") {
      if(!e.multiple && p.values.length !== 1)throw new Error("single_select_requires_one_value");
      const wanted=new Set(p.values);
      for(const value of wanted)if(![...e.options].some(o=>o.value === value && !o.disabled))throw new Error("option_unavailable");
      for(const option of e.options)option.selected=wanted.has(option.value);
      e.dispatchEvent(new Event("input",{bubbles:true}));e.dispatchEvent(new Event("change",{bubbles:true}));
      return {selected:[...e.selectedOptions].map(o=>o.value)};
    }
    throw new Error("interaction_unavailable");
  } catch(error) {return {error:String(error.message).slice(0,200)};}
}
