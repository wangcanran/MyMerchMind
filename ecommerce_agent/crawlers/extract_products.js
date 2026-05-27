(() => {
  const out = [];
  const seen = new Set();
  const anchors = Array.from(
    document.querySelectorAll(
      'a[href*="item.taobao.com/item.htm"],a[href*="detail.tmall.com/item.htm"]'
    )
  );
  for (const a of anchors) {
    const href = (a.href || a.getAttribute('href') || '').trim();
    if (!href || seen.has(href)) continue;
    seen.add(href);

    const card = a.closest('div[class*="Card"],div[class*="Content"],li,div');
    const cardText = (card?.innerText || '').trim();
    const title =
      (a.textContent || '').trim() ||
      cardText.split('\n').map(s => s.trim()).find(Boolean) ||
      '';

    const priceMatch = cardText.match(/¥\s*([0-9]+(?:\.[0-9]+)?)/);
    const salesMatch = cardText.match(/(已售\s*[0-9]+(?:\.[0-9]+)?(?:万\+?)?(?:件)?|[0-9]+(?:\.[0-9]+)?(?:万\+?)?人(?:看过|付款))/);
    const shopMatch = cardText.match(/([^\n]{2,40}(?:旗舰店|专营店|企业店|小店|店铺|店))/);

    out.push({
      title,
      price: priceMatch ? priceMatch[1] : '',
      sales: salesMatch ? salesMatch[1] : '',
      shop: shopMatch ? shopMatch[1] : '',
      url: href
    });
  }
  return out;
})()
