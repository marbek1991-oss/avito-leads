(() => {
  // Runs only on the fixed GitHub Pages application origin.
  if(window.__avitoLeadsBridgeLoaded)return;
  window.__avitoLeadsBridgeLoaded=true;
  const deliver=data=>{
    if(!data || !/^[0-9]{7,15}$/.test(String(data.itemId||'')))return;
    window.postMessage({type:'AVITO_LEADS_CARD_OBSERVED',payload:data},location.origin);
  };
  chrome.runtime.onMessage.addListener(msg=>{
    if(msg?.type==='AVITO_LEADS_CARD_UPDATE')deliver(msg.data);
  });
  // Application signals readiness after it registers the message listener.
  window.addEventListener('message',event=>{
    if(event.source!==window||event.origin!==location.origin||event.data?.type!=='AVITO_LEADS_READY')return;
    chrome.runtime.sendMessage({type:'AVITO_LEADS_GET_LAST'},response=>{
      if(chrome.runtime.lastError)return;
      if(response?.data)deliver(response.data);
    });
  });
})();