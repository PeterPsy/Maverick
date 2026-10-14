import { fixtureServer } from "./shell-presentation-fixture.mjs";
import { send } from "./browser-contract-support.mjs";

const appIds = ["chat", "storage", "calendar"];
const kinds = {
  "shell.sidebar.primary": "sidebar",
  "shell.sidebar.footer": "sidebar-footer",
  "shell.contextual.chat": "floating",
};

export function widgetLifecycleFixture() {
  const launches = [];
  const documents = [];
  const tickets = new Map();
  let serial = 0;
  const server = fixtureServer([], undefined, async (request, response, url, port) => {
    const json = (body) => send(response, JSON.stringify(body), "application/json");
    const readBody = async () => { let body = ""; for await (const chunk of request) body += chunk; return body; };
    if (url.pathname === "/api/apps") {
      json({ items: appIds.map((app_id) => ({ app_id, name: app_id, requires: [], provides: [],
        status: "enabled", frontend_role: "workspace", frontend_launchable: true, frontend_mount: `/apps/${app_id}/` })) });
    } else if (url.pathname === "/api/apps/app-store/backend") {
      json({ pinned_apps: appIds });
    } else if (url.pathname === "/api/apps/widgets") {
      const kind = url.searchParams.get("content_kind");
      json({ items: kinds[kind] ? (kind.startsWith("shell.sidebar") ? appIds : ["chat"]).map((owner) => ({
        owner_app_id: owner, widget_id: `${owner}-${kinds[kind]}`, host: "base-shell", content_kinds: [kind], actions: {},
        frontend_mount: `/api/apps/widgets/${owner}/${owner}-${kinds[kind]}/frontend/`,
      })) : [] });
    } else if (url.pathname === "/api/apps/widgets/context") {
      json({ context: {}, context_token: `fixture-context-${++serial}` });
    } else if (url.pathname === "/api/app-frames/browser-launch") {
      const body = JSON.parse(await readBody());
      launches.push(body.path);
      const ticket = `fixture-ticket-${++serial}`;
      tickets.set(ticket, body.path);
      const origin = `http://localhost:${port}`;
      json({ origin, bootstrap_url: `${origin}/.well-known/maverick-app-frame-bootstrap`,
        method: "POST", ticket, ticket_field: "ticket" });
    } else if (url.pathname === "/.well-known/maverick-app-frame-bootstrap") {
      const ticket = new URLSearchParams(await readBody()).get("ticket");
      const path = tickets.get(ticket);
      tickets.delete(ticket);
      send(response, "", "text/html", path ? 303 : 403, path ? { Location: path } : {});
    } else if (/^\/apps\/(chat|storage|calendar)\/$/.test(url.pathname) ||
      /^\/api\/apps\/widgets\/[^/]+\/[^/]+\/frontend\/$/.test(url.pathname)) {
      documents.push(url.pathname);
      const parts = url.pathname.split("/");
      const widget = parts[3] === "widgets";
      const owner = widget ? parts[4] : parts[2];
      const widgetId = widget ? parts[5] : "";
      send(response, frameDocument({ owner, widgetId, instance: ++serial, port }), "text/html");
    } else return false;
    return true;
  });
  return { server, launches, documents };
}

function frameDocument({ owner, widgetId, instance, port }) {
  return `<!doctype html><html><body style="margin:0"><textarea aria-label="Draft"></textarea>
    <div id="transcript" style="height:120px;overflow:auto"><div style="height:1600px">Transcript</div></div>
    <button id="dock">Dock chat</button><button id="overlay">Return to overlay</button><script>
    const owner=${JSON.stringify(owner)},widgetId=${JSON.stringify(widgetId)},platform="http://127.0.0.1:${port}";
    window.instance=${instance};window.visible=false;
    const post=data=>parent.postMessage({owner_app_id:owner,widget_id:widgetId,...data},platform);
    addEventListener("message",event=>{
      if(event.origin!==platform||event.source!==parent)return;
      if(event.data.type==="maverick.app.visibility-changed")window.visible=event.data.visible;
      if(event.data.type==="maverick.widget.context-changed")window.context=event.data.context;
      if(event.data.type==="maverick.widget.primary-action.query")post({type:"maverick.widget.primary-action.state",available:true,label:"New "+owner});
    });
    document.querySelector("#dock").onclick=()=>post({type:"maverick.widget.dock.open",placement:"right",params:{navigation_scope:"fixture-chat",thread_id:"fixture-thread"}});
    document.querySelector("#overlay").onclick=()=>post({type:"maverick.widget.dock.close"});
    if(widgetId.endsWith("floating"))post({type:"maverick.widget.resize",width:"420px",height:"400px"});
    post(widgetId?{type:"maverick.widget.ready"}:{type:"maverick.app.ready",app_id:owner});
    </script></body></html>`;
}
