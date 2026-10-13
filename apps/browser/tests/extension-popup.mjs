// Chrome action popups are DevTools targets outside Playwright's page list.
export async function openActionPopup(browser, extensionId, tabUrl) {
  const wait = async predicate => {
    for (let i=0;i<100;i++) { const result=await predicate();if(result)return result;await new Promise(resolve=>setTimeout(resolve,100)); }
    throw new Error("extension_popup_timeout");
  };
  const canonical=value=>value.replace(/^chrome:\/\/(newtab|new-tab-page)\//u,"chrome://newtab/");
  const tab=await wait(async()=>{
    const targets=(await browser.send("Target.getTargets",{filter:[{type:"tab"},{exclude:true}]})).targetInfos;
    return targets.find(target=>canonical(target.url) === canonical(tabUrl));
  });
  await browser.send("Extensions.triggerAction",{id:extensionId,targetId:tab.targetId});
  const popup=await wait(async()=> (await browser.send("Target.getTargets",{filter:[{}]})).targetInfos.find(target=>target.type === "page" && target.url.endsWith("/popup.html")));
  const {sessionId}=await browser.send("Target.attachToTarget",{targetId:popup.targetId,flatten:false});
  let serial=0;
  const send=(method,params={})=>new Promise((resolve,reject)=>{
    const id=++serial;
    const timer=setTimeout(()=>{browser.off("Target.receivedMessageFromTarget",receive);reject(new Error("popup_evaluation_timeout"));},10000);
    function receive(event) {
      if(event.sessionId !== sessionId)return;
      const result=JSON.parse(event.message);if(result.id !== id)return;
      clearTimeout(timer);browser.off("Target.receivedMessageFromTarget",receive);
      if(result.error)reject(new Error(JSON.stringify(result.error)));else resolve(result.result);
    }
    browser.on("Target.receivedMessageFromTarget",receive);
    browser.send("Target.sendMessageToTarget",{sessionId,message:JSON.stringify({id,method,params})}).catch(reject);
  });
  const evaluate=async expression=>{
    const result=await send("Runtime.evaluate",{expression,returnByValue:true,awaitPromise:true,userGesture:true});
    if(result.exceptionDetails)throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result?.value;
  };
  await wait(()=>evaluate("typeof document.querySelector('#share')?.onclick === 'function'"));
  return {evaluate,send,
    async detach(){await browser.send("Target.detachFromTarget",{sessionId}).catch(error=>{
      if(!error.message.includes("No session with given id"))throw error;
    });},
    async close(){await browser.send("Target.closeTarget",{targetId:popup.targetId}).catch(error=>{
      // Chrome destroys the popup when Open agent tab moves focus.
      if(!error.message.includes("No target with given id"))throw error;
    });}};
}
