'use strict';
// Data remains in the locally installed extension. It is not sent to GitHub.
const APP = 'https://marbek1991-oss.github.io/avito-leads/';
const validId = id => /^[0-9]{7,15}$/.test(String(id||''));
const validCard = data => {
  if(!data || !validId(data.itemId) || typeof data.description!=='string' || data.description.trim().length<100) return false;
  try {
    const u=new URL(data.sourceUrl);
    return u.protocol==='https:' && ['www.avito.ru','avito.ru'].includes(u.hostname) && u.pathname.endsWith('_'+data.itemId);
  }catch{return false}
};
function relay(data) {
  chrome.tabs.query({url:APP+'*'}, tabs=>{
    if(chrome.runtime.lastError)return;
    for (const tab of tabs||[]) {
      if(!tab.id)continue;
      chrome.tabs.sendMessage(tab.id,{type:'AVITO_LEADS_CARD_UPDATE',data},()=>void chrome.runtime.lastError);
    }
  });
}
chrome.runtime.onMessage.addListener((msg,sender,respond)=>{
  if(msg?.type==='AVITO_CARD_OBSERVED'){
    if(!sender.tab || !/^https:\/\/(?:www\.)?avito\.ru\//.test(sender.tab.url||'') || !validCard(msg.data))return;
    chrome.storage.local.set({lastAvitoCard:msg.data},()=>{
      if(chrome.runtime.lastError)return;
      relay(msg.data);
    });
    return;
  }
  if(msg?.type==='AVITO_LEADS_GET_LAST'){
    if (!/^https:\/\/marbek1991-oss\.github\.io\/avito-leads\//.test(sender.url||'')) return;
    chrome.storage.local.get('lastAvitoCard',result=>{
      respond({data:validCard(result?.lastAvitoCard)?result.lastAvitoCard:null});
    });
    return true;
  }
});