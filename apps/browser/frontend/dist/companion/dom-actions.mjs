// This fixed function runs in Chrome's isolated extension world, never with caller code.
export async function observe(action, p) {
  try {
  const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
  const finite = n => Number.isFinite(n) ? n : null;
  const video = () => {
    const element = document.querySelectorAll("video")[p.video_index ?? 0];
    if (!element?.getClientRects().length) throw new Error("video_unavailable");
    return element;
  };
  const metadata = element => {
    const r = element.getBoundingClientRect();
    return {duration_seconds: finite(element.duration), current_time_seconds: element.currentTime,
      ready_state: element.readyState, video_index: p.video_index ?? 0,
      rect: {x:r.x,y:r.y,width:r.width,height:r.height}, viewport: {width:innerWidth,height:innerHeight}};
  };
  const seek = async (element, time, presentFrame=true) => {
    if (time !== undefined) {
      if (!Number.isFinite(element.duration) || time >= element.duration) throw new Error("video_seek_out_of_range");
      element.currentTime = time;
    }
    const end = performance.now() + 10000;
    while ((element.seeking || element.readyState < 2) && performance.now() < end) await delay(50);
    if (element.seeking || element.readyState < 2) throw new Error("video_not_ready");
    if(!presentFrame)return null;
    // Chromium may retain an old compositor surface for a paused seek. A short
    // muted playback waits for a real newly presented decoded frame, then pauses.
    const target=time ?? element.currentTime;
    let callback,timer;
    const presented=new Promise(resolve=>{
      const frame=(_now,info)=>{
        // A queued callback can still describe the surface from before the seek.
        if(info.mediaTime >= target-0.05 && info.mediaTime <= target+0.4) {
          clearTimeout(timer);resolve(info.mediaTime);
        } else callback=element.requestVideoFrameCallback(frame);
      };
      callback=element.requestVideoFrameCallback(frame);
      timer=setTimeout(()=>{element.cancelVideoFrameCallback(callback);resolve(null);},10000);
    });
    const muted=element.muted;element.muted=true;
    let presentedTime;
    try {
      await element.play();
      presentedTime=await presented;
      if(presentedTime === null)throw new Error("video_presentation_timeout");
    } finally {clearTimeout(timer);element.cancelVideoFrameCallback(callback);element.pause();element.muted=muted;}
    await delay(150);
    return presentedTime;
  };
  if (["snapshot", "content.read"].includes(action)) {
    const result = globalThis.maverickBrowserRead({maxChars:p.max_chars ?? 40000,maxItems:p.max_items ?? 100});
    const redact = value => {if (!value) return null; const url = new URL(value);url.search="";url.hash="";return url.href;};
    for (const item of result.links) item.url = redact(item.url);
    for (const item of result.images) item.url = redact(item.url);
    for (const item of result.videos) {item.url = redact(item.url);item.poster_url = redact(item.poster_url);}
    return {...result,url:redact(location.href),observed_at:new Date().toISOString(),source:"shared_chrome_rendered_dom"};
  }
  if (action === "scroll") {
    let root = document.scrollingElement;
    if (p.target !== "document") {
      const candidates = [...document.querySelectorAll("main, [role=main], [role=dialog], section, div")].filter(e => {
        const r=e.getBoundingClientRect(); const s=getComputedStyle(e);
        return e.scrollHeight > e.clientHeight + 40 && e.clientHeight > 180 && r.width > 250 && r.bottom > 0 && r.top < innerHeight
          && ["auto","scroll"].includes(s.overflowY);
      });
      candidates.sort((a,b) => b.clientWidth*b.clientHeight-a.clientWidth*a.clientHeight);
      root = candidates[0] || root;
    }
    if (!root) throw new Error("scroll_unavailable");
    const position = () => ({top:root.scrollTop,height:root.scrollHeight,viewport_height:root.clientHeight});
    const before = position();
    for (let i=0;i<(p.steps ?? 1);i++) {
      root.scrollBy({top:(p.direction === "up" ? -1 : 1)*(p.pixels ?? 900),behavior:"instant"});
      await delay(p.settle_ms ?? 700);
    }
    const after = position();
    return {before,after,moved:before.top !== after.top,at_bottom:after.top+after.viewport_height >= after.height-2,
      target:root === document.scrollingElement ? "document" : "rendered_container"};
  }
  if (action === "wait_for") {
    const end=performance.now()+(p.timeout_ms ?? 5000);
    while (performance.now()<end) {
      if (document.readyState === "complete" || p.state !== "load" && document.readyState === "interactive") return {ready_state:document.readyState};
      await delay(50);
    }
    throw new Error("page_wait_timeout");
  }
  if (action === "video.prepare") {
    const element=video();
    if (globalThis.maverickVideoState) throw new Error("video_already_in_use");
    globalThis.maverickVideoState = [...document.querySelectorAll("video")].map(e => ({element:e,time:e.currentTime,paused:e.paused,muted:e.muted,volume:e.volume,rate:e.playbackRate}));
    for (const e of document.querySelectorAll("video")) e.pause();
    element.scrollIntoView({block:"center",inline:"center",behavior:"instant"});
    // There is no decoded frame at duration; replaying an ended video starts at
    // zero and can never present its old end timestamp within the seek deadline.
    const time=p.time_seconds ?? (element.ended || element.currentTime>=element.duration ? 0 : undefined);
    const presented=await seek(element,time);
    return {...metadata(element),presented_time_seconds:presented};
  }
  if (action === "video.seek") {const e=video();e.pause();const presented=await seek(e,p.time_seconds,p.present_frame !== false);return {...metadata(e),presented_time_seconds:presented};}
  if (action === "video.play") {
    const e=video();e.muted=false;e.volume=1;e.playbackRate=1;
    await e.play();return metadata(e);
  }
  if (action === "video.pause") {const e=video();e.pause();return metadata(e);}
  if (action === "video.restore") {
    for (const saved of globalThis.maverickVideoState || []) {
      const e=saved.element;
      if (!e.isConnected) continue;
      e.pause();e.muted=saved.muted;e.volume=saved.volume;e.playbackRate=saved.rate;
      if (Number.isFinite(e.duration)) e.currentTime=Math.min(saved.time,e.duration);
      if (!saved.paused) await e.play().catch(()=>{});
    }
    delete globalThis.maverickVideoState;
    return {restored:true};
  }
  throw new Error("observation_unavailable");
  } catch(error) {
    // Chrome scripting does not reliably propagate rejected async functions.
    return {error:"dom_observation_failed",detail:String(error.message).slice(0,300)};
  }
}
