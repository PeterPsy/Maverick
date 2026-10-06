let stream, audioContext, recorder, recording, recordingTimer;
const video=document.querySelector("video");
const base64 = async blob => {
  const bytes=new Uint8Array(await blob.arrayBuffer());let text="";
  for(let i=0;i<bytes.length;i+=8192) text+=String.fromCharCode(...bytes.subarray(i,i+8192));
  return btoa(text);
};
const stop = async () => {
  clearTimeout(recordingTimer);
  if (recorder?.state === "recording") recorder.stop();
  for(const track of stream?.getTracks() || []) track.stop();
  stream=null;video.srcObject=null;
  if(audioContext) await audioContext.close();audioContext=null;
};
async function capture(action,p) {
  if(action === "stop") {await stop();return {stopped:true};}
  if(action === "start") {
    await stop();
    stream=await navigator.mediaDevices.getUserMedia({audio:{mandatory:{chromeMediaSource:"tab",chromeMediaSourceId:p.streamId}},video:{mandatory:{chromeMediaSource:"tab",chromeMediaSourceId:p.streamId}}});
    video.srcObject=stream;await video.play();
    if(stream.getAudioTracks().length) {
      audioContext=new AudioContext();audioContext.createMediaStreamSource(stream).connect(audioContext.destination);await audioContext.resume();
    }
    return {capturing:true};
  }
  if(!stream?.getTracks().some(t=>t.readyState === "live")) throw new Error("tab_capture_unavailable");
  if(action === "status") return {capturing:true,recording:recorder?.state === "recording"};
  if(action === "frame") {
    if(typeof p.image_data_url !== "string" || !p.image_data_url.startsWith("data:image/jpeg;base64,") || p.image_data_url.length>8*1024*1024) throw new Error("invalid_tab_screenshot");
    const bitmap=await createImageBitmap(await (await fetch(p.image_data_url)).blob());
    let rect={x:0,y:0,width:bitmap.width,height:bitmap.height};
    if(p.rect) {
      const scaleX=bitmap.width/p.viewport.width,scaleY=bitmap.height/p.viewport.height;
      const r=p.rect;
      if(r.x < -1 || r.y < -1 || r.x+r.width > p.viewport.width+1 || r.y+r.height > p.viewport.height+1 || r.width<2 || r.height<2) throw new Error("video_not_fully_visible");
      rect={x:Math.max(0,r.x*scaleX),y:Math.max(0,r.y*scaleY),width:r.width*scaleX,height:r.height*scaleY};
    }
    const factor=Math.min(1,1280/Math.max(rect.width,rect.height));
    const canvas=document.createElement("canvas");canvas.width=Math.round(rect.width*factor);canvas.height=Math.round(rect.height*factor);
    canvas.getContext("2d").drawImage(bitmap,rect.x,rect.y,rect.width,rect.height,0,0,canvas.width,canvas.height);
    bitmap.close();
    const blob=await new Promise(r=>canvas.toBlob(r,"image/jpeg",0.72));
    return {mime_type:"image/jpeg",base64:await base64(blob),width:canvas.width,height:canvas.height,source:"shared_tab_screenshot"};
  }
  if(action === "audio.start") {
    if(recording || !stream.getAudioTracks().length) throw new Error("audio_capture_unavailable");
    const mimeType=["audio/webm;codecs=opus","audio/webm"].find(t=>MediaRecorder.isTypeSupported(t));
    if(!mimeType) throw new Error("audio_codec_unavailable");
    if(typeof p.max_seconds !== "number" || !Number.isFinite(p.max_seconds) || p.max_seconds <= 0 || p.max_seconds > 180) throw new Error("invalid_recording_duration");
    const audioStream=new MediaStream(stream.getAudioTracks());
    recorder=new MediaRecorder(audioStream,{mimeType,audioBitsPerSecond:64000});
    const chunks=[];let bytes=0,overflow=false;const started=performance.now();
    recorder.ondataavailable=e=>{bytes+=e.data.size;if(bytes>2*1024*1024){overflow=true;recorder.stop();}else if(e.data.size)chunks.push(e.data);};
    recording=new Promise((resolve,reject)=>{
      recorder.onstop=async()=>{try{if(overflow)throw new Error("audio_budget_exceeded");const duration=Math.min(p.max_seconds,(performance.now()-started)/1000);const blob=new Blob(chunks,{type:mimeType});resolve({content_type:"audio/webm",base64:await base64(blob),size_bytes:blob.size,duration_seconds:duration,source:"shared_tab_audio"});}catch(e){reject(e);}};
      recorder.onerror=()=>reject(new Error("audio_recording_failed"));
    });
    recorder.start(500);
    recordingTimer=setTimeout(()=>{if(recorder?.state === "recording")recorder.stop();},Math.max(50,(p.max_seconds-0.2)*1000));
    return {recording:true};
  }
  if(action === "audio.stop") {
    clearTimeout(recordingTimer);
    if(!recording) throw new Error("audio_not_recording");
    if(recorder.state === "recording")recorder.stop();
    try{return await recording;}finally{recording=null;recorder=null;}
  }
  throw new Error("capture_action_unavailable");
}
chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  if(sender.id !== chrome.runtime.id || message.target !== "offscreen") return;
  capture(message.action,message.parameters || {}).then(reply).catch(e=>reply({error:e.message}));return true;
});
