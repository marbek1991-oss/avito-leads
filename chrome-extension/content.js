(() => {
  let sent = '';
  function text(v){return String(v||'').replace(/\s+/g,' ').trim()}
  function extract(){
    const match=location.pathname.match(/_([0-9]{7,15})\/?$/);
    if(!match)return null;
    const id=match[1];
    let title=text(document.querySelector('h1')?.textContent);
    const descNode=document.querySelector('[data-marker="item-view/item-description"]') || document.querySelector('[data-marker="item-view/item-description-text"]');
    let description=text(descNode?.innerText || descNode?.textContent);
    let structured;
    for(const node of document.querySelectorAll('script[type="application/ld+json"]')){
      try{
        const obj=JSON.parse(node.textContent);
        const arr=Array.isArray(obj)?obj:[obj];
        structured=arr.find(x=>x&&typeof x==='object'&&typeof x.description==='string'&&x.description.length>40);
        if(structured)break;
      }catch{}
    }
    if(!description&&structured)description=text(structured.description);
    if(!title&&structured)title=text(structured.name);
    if(!title||!description)return null;
    const images=document.querySelectorAll('[data-marker^="image-frame/"] img, [data-marker="image-frame"] img');
    // Image count is only recorded when gallery picture nodes explicitly exist.
    const photos=images.length?images.length:null;
    return {itemId:id,name:title.slice(0,200),description:description.slice(0,20000),photos,sourceUrl:location.origin+location.pathname,observedAt:new Date().toISOString()};
  }
  function send(){
    const data=extract();if(!data)return;
    const signature=data.itemId+'|'+data.description.length+'|'+data.photos;
    if(signature===sent)return;sent=signature;
    chrome.runtime.sendMessage({type:'AVITO_CARD_OBSERVED',data},()=>void chrome.runtime.lastError);
  }
  send();
  let attempts=0;
  const observer=new MutationObserver(()=>{if(++attempts<100)send();else observer.disconnect()});
  observer.observe(document.documentElement,{childList:true,subtree:true});
  setTimeout(()=>observer.disconnect(),20000);
})();