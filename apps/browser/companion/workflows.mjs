import {instagramUrl} from "./scope.mjs";

export function contentGate(observation) {
  const text=(observation.text || "").toLowerCase();
  if (/challenge|checkpoint/u.test(new URL(observation.url).pathname)) return "challenge";
  if (/accounts\/login/u.test(new URL(observation.url).pathname) || /log in to continue|accedi per continuare/u.test(text)) return "login_required";
  if (/please wait a few minutes|riprova più tardi|try again later/u.test(text)) return "rate_limited";
  if (/page isn't available|pagina non è disponibile|sorry, this page/u.test(text)) return "page_unavailable";
  return null;
}

export async function collectInstagram(adapter,p) {
  const maxItems=p.max_items ?? 60,maxBatches=p.max_batches ?? 12;
  const base=instagramUrl(`https://www.instagram.com/${p.username}/`);
  const items=new Map(),batches=[],sections=p.include_reels === false ? [base] : [base,`${base}reels/`];
  const sectionResults=sections.map(source_url=>({source_url,status:"skipped",batches:0,stop_reason:null}));
  let profile=null,blocked=null,used=0;
  outer: for(const [sectionIndex,section] of sections.entries()) {
    if(used>=maxBatches || items.size>=maxItems)break;
    const summary=sectionResults[sectionIndex],remainingSections=sections.length-sectionIndex;
    // Reserve scans and item capacity for each requested section. Unused capacity
    // from a short profile is available to the following Reels section.
    const batchBudget=Math.ceil((maxBatches-used)/remainingSections);
    const itemLimit=items.size+Math.ceil((maxItems-items.size)/remainingSections);
    await adapter.navigate(section);
    let stagnant=0;
    while(summary.batches < batchBudget) {
      adapter.check();
      const observation=await adapter.read({max_chars:40000,max_items:200});
      summary.status="observed";
      used++;summary.batches++;
      if(!profile) profile=observation;
      const gate=contentGate(observation);
      if(gate){blocked=gate;summary.stop_reason=gate;break outer;}
      const before=items.size;
      for(const link of observation.links) {
        let url;try{url=instagramUrl(link.url);}catch{continue;}
        if(!/^https:\/\/www\.instagram\.com\/(p|reel)\//u.test(url) || items.has(url))continue;
        items.set(url,{url,kind:url.includes("/reel/") ? "reel" : "post",text:link.text,observed_at:observation.observed_at,found_on:section});
        if(items.size>=itemLimit)break;
      }
      batches.push({source_url:section,observed_at:observation.observed_at,new_items:items.size-before});
      if(items.size>=itemLimit){summary.stop_reason=items.size>=maxItems ? "item_limit" : "section_item_limit";break;}
      if(summary.batches>=batchBudget){summary.stop_reason=used>=maxBatches ? "batch_limit" : "section_batch_limit";break;}
      const scrolling=await adapter.scroll({direction:"down",pixels:1000,steps:1,settle_ms:1200,target:"auto"});
      stagnant=items.size===before && scrolling.at_bottom && !scrolling.moved ? stagnant+1 : 0;
      if(stagnant>=3){summary.stop_reason="rendered_end";break;}
    }
  }
  const stopReason=blocked || (items.size>=maxItems ? "item_limit" : used>=maxBatches ? "batch_limit" :
    sectionResults.every(section=>section.stop_reason === "rendered_end") ? "rendered_end" : "section_limit");
  for(const section of sectionResults)if(section.status === "skipped")section.stop_reason=stopReason;
  return {username:p.username,source_url:base,profile,items:[...items.values()],batches,sections:sectionResults,stop_reason:stopReason,
    observed_at:new Date().toISOString(),coverage:"Only rendered links observed during bounded scrolling. Each post/Reel must be opened to inspect its full content. Private, unavailable and unvisited content is excluded."};
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
      observed_at:new Date().toISOString(),source:"user_shared_chrome",coverage:"Sampled visible frames and, when requested, audio actually played in the shared tab. A transcript is generated locally by Maverick Speech."};
  } finally {
    const cleanup=adapter.cleanup || ((a,p)=>a === "video.restore" ? adapter.dom(a,p) : adapter.capture(a,p));
    if(recording)await cleanup("audio.stop",{}).catch(()=>{});
    await cleanup("video.restore",{video_index:index}).catch(()=>{});
  }
}
