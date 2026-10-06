import "./style.css";
import {request} from "./api.js";
import {createConnector} from "./connector.js";

const connectorMode=new URLSearchParams(location.search).get("connector") === "1";
document.querySelector("#app").innerHTML=`<main><header><img src="${new URL("../public/icon.svg",import.meta.url).href}" alt="" width="36" height="36"><div><h1>Browser</h1><p>Instagram · navigazione e analisi</p></div><span class="badge">Sola lettura</span></header>
<section class="panel"><h2>${connectorMode ? "Collega la scheda condivisa" : "Usa Instagram da Maverick"}</h2><p>Il Browser legge il profilo, i post e i Reel dalla tua scheda Chrome autenticata. Può scorrere, acquisire fotogrammi e trascrivere l’audio localmente.</p>
<ol><li>Scarica ed estrai <a id="download" download="maverick-browser-companion.zip">Browser Companion</a>. In <code>chrome://extensions</code> attiva “Modalità sviluppatore” e scegli “Carica estensione non pacchettizzata”.</li>
<li>Copia l’indirizzo qui sotto. Apri un profilo, post o Reel Instagram in Chrome, poi apri l’estensione e condividi la scheda.</li><li>Nella finestra Browser aperta dall’estensione premi “Collega”. Tieni la finestra aperta mentre lavori in Chat.</li></ol>
<div class="copy"><input id="url" readonly aria-label="Indirizzo di collegamento"><button id="copy">Copia indirizzo</button></div>
<div class="actions"><button id="connect">Collega</button><button id="stop" class="secondary" hidden>Interrompi condivisione</button></div><p id="status" class="status" role="status">${connectorMode ? "Pronto per collegare la scheda scelta nell’estensione." : "Le schede condivise compariranno qui."}</p></section>
<section class="panel"><div class="section-title"><h2>Schede e operazioni</h2><button id="refresh" class="secondary">Aggiorna</button></div><div id="connections"></div><div id="operations"></div></section>
<footer>Login e verifica Instagram avvengono nella tua scheda. La condivisione termina quando la chiudi, esci dalle pagine consentite o premi “Interrompi”.</footer></main>`;
const $=s=>document.querySelector(s);
const url=new URL(location.href);url.search="?connector=1";url.hash="";$("#url").value=url.href;
// import.meta.url belongs to the public platform mount even in an isolated app frame.
$("#download").href=new URL(/* @vite-ignore */ "../maverick-browser-companion.zip",import.meta.url).href;
$("#copy").onclick=async()=>{try{await navigator.clipboard.writeText(url.href);$("#status").textContent="Indirizzo copiato.";}catch{$("#url").select();$("#status").textContent="Seleziona e copia l’indirizzo.";}};
const connector=createConnector(text=>{$("#status").textContent=text;});
$("#connect").hidden=!connectorMode;
$("#connect").onclick=async()=>{
  $("#connect").disabled=true;
  try{await connector.start();$("#stop").hidden=false;$("#connect").hidden=true;await refresh();}
  catch(error){$("#status").textContent=error.message;$("#connect").disabled=false;}
};
$("#stop").onclick=async()=>{await connector.stop();$("#stop").hidden=true;$("#connect").hidden=false;$("#connect").disabled=false;await refresh();};
function row(text,detail,action) {
  const div=document.createElement("div");div.className="row";
  const content=document.createElement("div"),strong=document.createElement("strong"),small=document.createElement("small");strong.textContent=text;small.textContent=detail;content.append(strong,small);div.append(content);
  if(action){const button=document.createElement("button");button.className="secondary";button.textContent=action.label;button.onclick=action.run;div.append(button);}return div;
}
async function refresh() {
  try {
    const overview=await request({action:"companion.overview"});$("#connections").replaceChildren();$("#operations").replaceChildren();
    if(!overview.connections.length)$("#connections").append(row("Nessuna scheda condivisa","Collega Chrome seguendo i passaggi sopra."));
    for(const c of overview.connections)$("#connections").append(row(`${c.display_name} · ${c.status}`,`${c.url || "In attesa di Chrome"} · ${c.session_id}`,["connecting","connected","offline"].includes(c.status) ? {label:"Revoca",run:async()=>{await request({action:"companion.disconnect",session_id:c.session_id});await refresh();}} : null));
    for(const op of overview.operations)$("#operations").append(row(`${op.action} · ${op.status}`,`${op.operation_id} · ${new Date(op.created_at*1000).toLocaleString()}`,["queued","running","processing_media"].includes(op.status) ? {label:"Annulla",run:async()=>{await request({action:"operation.cancel",operation_id:op.operation_id});await refresh();}} : {label:"Risultato",run:async()=>{const result=await request({action:"operation.get",operation_id:op.operation_id});showResult(result);}}));
  } catch(error){$("#status").textContent=error.message;}
}
function showResult(result) {
  document.querySelector("dialog")?.remove();const dialog=document.createElement("dialog");const close=document.createElement("button");close.textContent="Chiudi";close.onclick=()=>dialog.close();const pre=document.createElement("pre");
  pre.textContent=JSON.stringify(result,(key,value)=>key === "base64" ? "[media acquisito]" : value,2);dialog.append(close,pre);document.body.append(dialog);dialog.showModal();
}
$("#refresh").onclick=refresh;void refresh();
setInterval(()=>{if(document.visibilityState !== "hidden")void refresh();},10000);
