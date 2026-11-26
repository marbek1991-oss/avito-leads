(() => {
  'use strict';
  if (window.__avitoLeadsExtractorLoaded) return;
  window.__avitoLeadsExtractorLoaded = true;

  const clean = value => String(value ?? '').replace(/\s+/g, ' ').trim();
  const idMatch = () => location.pathname.match(/_([0-9]{7,15})\/?$/);
  const tag = sel => document.querySelector(sel);
  const safePrice = val => clean(val).slice(0,100);
  let last = '';
  let observed = 0;

  function structuredListing() {
    for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const parsed = JSON.parse(script.textContent);
        const walk = [parsed];
        while (walk.length) {
          const obj = walk.shift();
          if (Array.isArray(obj)) {walk.push(...obj); continue}
          if (!obj || typeof obj !== 'object') continue;
          if (Array.isArray(obj['@graph'])) walk.push(...obj['@graph']);
          if (typeof obj.description === 'string' && obj.description.length >= 40) return obj;
        }
      } catch {}
    }
    return null;
  }

  function getCard() {
    const m = idMatch();
    if (!m) return null;
    const id = m[1], structured = structuredListing();
    const title = clean(tag('h1')?.innerText || tag('h1')?.textContent || structured?.name);
    const candidates = [
      '[data-marker="item-view/item-description"]',
      '[data-marker="item-view/item-description-text"]',
      '[itemprop="description"]',
      '[data-marker*="description"]'
    ];
    let desc = '';
    for (const selector of candidates) {
      const nodes = Array.from(document.querySelectorAll(selector));
      const longest = nodes.map(el=>clean(el.innerText || el.textContent)).sort((a,b)=>b.length-a.length)[0] || '';
      if (longest.length > desc.length && longest.length < 25000) desc = longest;
    }
    if (desc.length < 100 && typeof structured?.description === 'string') {
      const fromStructured = clean(structured.description);
      if (fromStructured.length > desc.length) desc = fromStructured;
    }
    // A card can't be audited if its actual description isn't available.
    if (!title || desc.length < 100) return null;

    let price = '';
    const priceNode=tag('[data-marker="item-view/item-price"]')||tag('[itemprop="price"]');
    if (priceNode) price = safePrice(priceNode.getAttribute('content') || priceNode.innerText || priceNode.textContent);
    if (!price) price = safePrice(structured?.offers?.price || structured?.offers?.lowPrice);
    const locationNode=tag('[data-marker="item-view/item-address"]');
    const city=clean(locationNode?.innerText || locationNode?.textContent).slice(0,120);
    const gallery=document.querySelectorAll('[data-marker^="image-frame/"] img, [data-marker="image-frame"] img, [data-marker*="image-frame"] img');
    const photoElements=Array.from(gallery).filter(el=>el.currentSrc || el.getAttribute('src')).length;
    const photos=photoElements || null;
    return {
      itemId:id, name:title.slice(0,200), description:desc.slice(0,20000),
      price, city, photos, photoCountSource:photoElements?'visible_gallery':'not_available',
      sourceUrl:location.origin+location.pathname,
      observedAt:new Date().toISOString()
    };
  }

  function update() {
    const card=getCard();
    if(!card)return;
    const sig=[card.itemId,card.description,card.price,card.photos].join('|');
    if(sig===last)return;
    last=sig;
    chrome.runtime.sendMessage({type:'AVITO_CARD_OBSERVED',data:card},()=>void chrome.runtime.lastError);
  }

  update();
  const observer=new MutationObserver(()=>{
    if (++observed % 7 === 0) update();
    if(observed>1200)observer.disconnect();
  });
  observer.observe(document.documentElement,{childList:true,subtree:true});
  [800,2000,4500,9000,14000].forEach(ms=>setTimeout(update,ms));
  setTimeout(()=>observer.disconnect(),20000);
})();