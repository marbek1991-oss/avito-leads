"""Импорт списка кандидатов из разрешённого JSON-источника.
Не обращается к Авито и не обходит ограничения сайта.
Переменная LEADS_FEED_URL должна указывать на собственный или разрешённый HTTPS JSON feed.
"""
import datetime as dt
import json
import os
import pathlib
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import re
import html

OUT = pathlib.Path("candidates.json")
url = os.environ.get("LEADS_FEED_URL", "").strip()
rss_url = os.environ.get("GOOGLE_ALERTS_RSS_URL", "").strip()
today = dt.datetime.now(dt.timezone.utc).isoformat()

def is_avito_link(value):
    try:
        p = urllib.parse.urlparse(str(value))
        return p.scheme == "https" and (p.hostname == "avito.ru" or (p.hostname or "").endswith(".avito.ru")) and len(p.path.strip("/").split("/")) >= 2
    except ValueError:
        return False

if not url and not rss_url:
    print("Источник не подключён: укажи LEADS_FEED_URL или GOOGLE_ALERTS_RSS_URL в GitHub Variables.")
    raise SystemExit(0)

def get_bytes(address):
    parsed = urllib.parse.urlparse(address)
    if parsed.scheme != "https" or not parsed.netloc:
        raise SystemExit("Адрес источника должен начинаться с https://")
    req = urllib.request.Request(address, headers={"User-Agent": "AvitoLeadsFeedImporter/1.1", "Accept": "application/json, application/atom+xml, application/rss+xml"})
    with urllib.request.urlopen(req, timeout=25) as response:
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise SystemExit("Слишком большой ответ источника")
    return data

items = []
if url:
    feed = json.loads(get_bytes(url))
    values = feed.get("items", []) if isinstance(feed, dict) else feed
    if not isinstance(values, list):
        raise SystemExit("JSON-источник должен содержать массив items")
    items.extend(values)

if rss_url:
    parsed = urllib.parse.urlparse(rss_url)
    if parsed.hostname not in ("www.google.com", "google.com", "www.google.ru", "google.ru") or not parsed.path.startswith("/alerts/feeds/"):
        raise SystemExit("GOOGLE_ALERTS_RSS_URL должен быть адресом RSS из Google Alerts")
    root = ET.fromstring(get_bytes(rss_url))
    entries = root.findall("{http://www.w3.org/2005/Atom}entry")
    for entry in entries:
        link_node = entry.find("{http://www.w3.org/2005/Atom}link")
        link = link_node.get("href", "") if link_node is not None else ""
        target = urllib.parse.urlparse(link)
        # Google Alerts usually links directly to the result. Do not follow third-party redirects.
        if target.hostname in ("www.google.com", "google.com"):
            params = urllib.parse.parse_qs(target.query)
            link = params.get("url", params.get("q", [""]))[0]
        if not is_avito_link(link):
            continue
        title = html.unescape(re.sub(r"<[^>]*>", "", entry.findtext("{http://www.w3.org/2005/Atom}title") or "")).strip()
        slug = urllib.parse.urlparse(link).path.strip("/").split("/")
        city = slug[0].replace("_", " ").title() if slug else ""
        title_lower = title.lower()
        niches = [
            ("Модульные дома", ("модульн", "домокомплект")),
            ("Строительство бань", ("баня", "бани", "бань")),
            ("Бытовки / вагончики", ("бытовк", "вагончик", "блок контейнер")),
            ("Стройматериалы", ("стройматериал", "кирпич", "газоблок")),
            ("Заборы / ворота", ("забор", "ворот")),
            ("Наружная реклама", ("вывеск", "наружн", "объёмные буквы"))
        ]
        niche = next((n for n, terms in niches if any(t in title_lower for t in terms)), "Другое")
        items.append({"name": title[:200] or "Объявление из Google Alerts", "city": city or "Не определён", "niche": niche,
                      "url": link, "issues": "", "recommend": "", "source": "Google Alerts RSS (поисковый индекс)",
                      "verification": "Не проверено: найдено в Google, а не непосредственно на Авито"})
previous = {}
if OUT.exists():
    try:
        prev = json.loads(OUT.read_text(encoding="utf-8"))
        previous = {i["url"].split("?")[0]: i for i in prev.get("items", []) if isinstance(i, dict) and isinstance(i.get("url"), str)}
    except (ValueError, OSError, KeyError):
        pass
allowed = {"Модульные дома","Строительство бань","Бытовки / вагончики","Стройматериалы","Заборы / ворота","Наружная реклама"}
new = []
seen = set(previous)
for x in items:
    if not isinstance(x, dict):
        continue
    link = str(x.get("url", "")).strip()
    key = link.split("?")[0]
    if not is_avito_link(link) or key in seen:
        continue
    name = str(x.get("name", "")).strip()[:200]
    city = str(x.get("city", "")).strip()[:100]
    niche = str(x.get("niche", "")).strip()[:100]
    if not (name and city and niche):
        continue
    seen.add(key)
    new.append({
        "url": link, "name": name, "city": city, "niche": niche,
        "issues": str(x.get("issues", "")).strip()[:1200],
        "recommend": str(x.get("recommend", "")).strip()[:1200],
        "verification": str(x.get("verification", "Не проверено на Авито"))[:180],
        "source": str(x.get("source", "Внешний источник"))[:200],
        "added_at": today
    })
    if len(new) == 15:
        break
all_items = (new + list(previous.values()))[:300]
OUT.write_text(json.dumps({"generated_at": today, "source_configured": True, "new_count": len(new),
                           "disclaimer": "Ссылки получены из внешнего источника или Google Alerts; открытость и актуальность объявлений на Авито не проверены.",
                           "items": all_items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Получено {len(new)} новых кандидатов от настроенного источника. Актуальность Авито не утверждается.")
