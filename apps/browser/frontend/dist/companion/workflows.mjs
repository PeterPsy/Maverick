import {platformUrl,platformForUrl} from "./scope.mjs";

const itemPaths={instagram:/^\/(p|reel)\//u,twitter:/\/(status|article)\//u,reddit:/\/comments\//u,
  facebook:/\/(posts|videos|reel)\//u,linkedin:/^\/(posts|feed\/update|jobs\/view)\//u,
  youtube:/^\/(watch|shorts\/)/u};

export async function collectContent(adapter,p) {
  const urls=p.urls.map(url=>platformUrl(url)),source=platformForUrl(urls[0]);
  const maxItems=p.max_items ?? 60,maxBatches=p.max_batches ?? 12;
  const items=new Map(),observations=[],sections=[];let used=0,blocked=null;
  for(const [index,url] of urls.entries()) {
    const summary={source_url:url,batches:0,status:"skipped",stop_reason:"budget_exhausted"};sections.push(summary);
    if(used>=maxBatches || items.size>=maxItems)continue;
    const batchBudget=Math.ceil((maxBatches-used)/(urls.length-index));
    const itemBudget=items.size+Math.ceil((maxItems-items.size)/(urls.length-index));
    await adapter.navigate(url);let stagnant=0;
    while(summary.batches<batchBudget) {
      adapter.check();const observation=await adapter.read({max_chars:40000,max_items:200});
      used++;summary.batches++;summary.status="observed";
      if(summary.batches === 1)observations.push(observation);
      const gate=contentGate(observation);
      if(gate){blocked=gate;summary.stop_reason=gate;break;}
      const before=items.size;
      for(const link of observation.links || []) {
        let canonical;try{canonical=platformUrl(link.url,source);}catch{continue;}
        if(!itemPaths[source]?.test(new URL(canonical).pathname) || items.has(canonical))continue;
        items.set(canonical,{url:canonical,text:String(link.text || "").slice(0,2000),observed_at:observation.observed_at,found_on:url,
          kind:canonical.includes("/reel/") || canonical.includes("/shorts/") ? "video" : "item",content_observed:false});
        if(items.size>=itemBudget)break;
      }
      if(items.size>=itemBudget){summary.stop_reason=items.size>=maxItems ? "item_limit" : "section_item_limit";break;}
      if(summary.batches>=batchBudget){summary.stop_reason=used>=maxBatches ? "batch_limit" : "section_batch_limit";break;}
      const scroll=await adapter.scroll({direction:"down",pixels:1000,steps:1,settle_ms:1200,target:"auto"});
      stagnant=items.size === before && scroll.at_bottom && !scroll.moved ? stagnant+1 : 0;
      if(stagnant>=3){summary.stop_reason="rendered_end";break;}
    }
    if(blocked)break;
  }
  return {source,source_url:urls[0],observations,items:[...items.values()],sections,batches:used,
    stop_reason:blocked || (items.size>=maxItems ? "item_limit" : used>=maxBatches ? "batch_limit" : "rendered_boundary"),
    observed_at:new Date().toISOString(),coverage:"Links observed during bounded scrolling. Item content is not observed until each item is opened; rendered boundaries do not establish complete feed coverage."};
}

export function contentGate(observation) {
  const text=(observation.text || "").toLowerCase();
  if (/challenge|checkpoint/u.test(new URL(observation.url).pathname)) return "challenge";
  if (/accounts\/login/u.test(new URL(observation.url).pathname) || /log in to continue|accedi per continuare|sign in to continue|请先登录/u.test(text)) return "login_required";
  if (/please wait a few minutes|riprova più tardi|try again later/u.test(text)) return "rate_limited";
  if (/page isn't available|pagina non è disponibile|sorry, this page/u.test(text)) return "page_unavailable";
  return null;
}

export async function analyzeVideo(adapter,p) {
  const index=p.video_index ?? 0,count=p.frame_count ?? 6,limit=p.max_seconds ?? 90;
  const frames=[];let audio=null,recording=false;
  try {
    const prepared=await adapter.dom("video.prepare",{video_index:index,time_seconds:0});
    const duration=prepared.duration_seconds;
    if(!Number.isFinite(duration) || duration<=0) throw new Error("finite_video_duration_required");
    const covered=Math.min(duration,limit);
    for(let i=0;i<count;i++) {
      adapter.check();
      const time=count===1 ? Math.min(covered/2,duration-0.05) : Math.max(0,(covered-0.05)*i/(count-1));
      const timing=await adapter.dom("video.seek",{video_index:index,time_seconds:time});
      frames.push({...await adapter.capture("frame",timing),time_seconds:timing.presented_time_seconds ?? timing.current_time_seconds,
        requested_time_seconds:time,observed_at:new Date().toISOString()});
    }
    if(p.include_audio !== false) {
      await adapter.dom("video.seek",{video_index:index,time_seconds:0,present_frame:false});
      await adapter.capture("audio.start",{max_seconds:covered});recording=true;
      const playing=await adapter.dom("video.play",{video_index:index});
      const audioStart=playing.current_time_seconds;
      const started=Date.now();let last=audioStart,stalled=0;
      while(Date.now()-started < covered*1000) {
        adapter.check();await adapter.delay(500);
        // Sampling playback position without pausing is a fixed observation.
        const observation=await adapter.read({max_chars:1,max_items:200});
        const current=observation.videos.find(v=>v.video_index===index)?.current_time_seconds;
        if(current === undefined)throw new Error("video_disappeared");
        if(current>=covered-0.15){last=current;break;}
        stalled=current<=last+0.01 ? stalled+1 : 0;last=current;
        if(stalled>20)throw new Error("video_playback_stalled");
      }
      await adapter.dom("video.pause",{video_index:index});
      const recorded=await adapter.capture("audio.stop",{});
      audio={...recorded,start_time_seconds:audioStart,
        end_time_seconds:Math.min(covered,last,audioStart+recorded.duration_seconds),
        playback_end_time_seconds:last};recording=false;
    }
    return {video_index:index,duration_seconds:duration,covered_seconds:covered,truncated:duration>covered,frames,audio,
      observed_at:new Date().toISOString(),source:"user_shared_chrome",coverage:"Sampled visible frames and, when requested, audio actually played in the shared tab. A transcript is generated locally by Loopino Speech."};
  } finally {
    const cleanup=adapter.cleanup || ((a,p)=>a === "video.restore" ? adapter.dom(a,p) : adapter.capture(a,p));
    if(recording)await cleanup("audio.stop",{}).catch(()=>{});
    await cleanup("video.restore",{video_index:index}).catch(()=>{});
  }
}
