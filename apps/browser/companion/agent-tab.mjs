import {platforms} from "./platforms.mjs";

// Identity is navigation metadata, never sharing authority. It survives stop and
// worker suspension in this Chrome session; closing the source forgets it.
export function createAgentTabRegistry(chrome, startUrl, newId = () => crypto.randomUUID()) {
  const get = async () => (await chrome.storage.session.get("agentTab")).agentTab;
  const remember = async tab => {
    const previous = await get();
    const identity = previous?.tabId === tab.id ? previous
      : {id:newId(), tabId:tab.id, allowedPlatforms:Object.keys(platforms)};
    await chrome.storage.session.set({agentTab:identity});
    return identity;
  };
  const forget = async tabId => {
    if ((await get())?.tabId === tabId) await chrome.storage.session.remove("agentTab");
  };
  return {get, remember, forget,
    async open() {
      const identity = await get();
      let tab;
      if (identity) {
        try {tab = await chrome.tabs.get(identity.tabId);}
        catch {await forget(identity.tabId);}
      }
      if (!tab) {
        const candidates = await chrome.tabs.query({url:startUrl});
        tab = candidates.sort((a,b)=>(b.lastAccessed || 0)-(a.lastAccessed || 0))[0];
      }
      tab = tab ? await chrome.tabs.update(tab.id,{active:true}) : await chrome.tabs.create({url:startUrl});
      await remember(tab);
      await chrome.windows.update(tab.windowId,{focused:true});
      return tab;
    },
  };
}
