chrome.runtime.onMessage.addListener((msg,sender)=>{
 if(msg?.type!=='AVITO_CARD_OBSERVED'||!sender.tab?.url)return;
 const d=msg.data||{};
 if(!/^[0-9]{7,15}$/.test(String(d.itemId||''))||typeof d.description!=='string'||d.description.length<40)return;
 chrome.tabs.query({url:"https://marbek1991-oss.github.io/avito-leads/*"},tabs=>{
  if(chrome.runtime.lastError)return;
  for(const tab of tabs||[]){
   if(!tab.id)continue;
   chrome.scripting.executeScript({target:{tabId:tab.id},func:(payload)=>{
    window.postMessage({type:'AVITO_LEADS_CARD_OBSERVED',payload},location.origin);
   },args:[d]},()=>void chrome.runtime.lastError);
  }
 });
});