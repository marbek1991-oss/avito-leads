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
# One or more RSS URLs separated by newlines, commas or semicolons.
# Existing single-feed configuration remains supported.
raw_rss = "\n".join(filter(None, (
    os.environ.get("GOOGLE_ALERTS_RSS_URL", ""),
    os.environ.get("GOOGLE_ALERTS_RSS_URLS", "")
)))
rss_urls = list(dict.fromkeys(x.strip() for x in re.split(r"[\n;,]+", raw_rss) if x.strip()))
today = dt.datetime.now(dt.timezone.utc).isoformat()

def is_avito_link(value):
    try:
        p = urllib.parse.urlparse(str(value))
        return p.scheme == "https" and (p.hostname == "avito.ru" or (p.hostname or "").endswith(".avito.ru")) and len(p.path.strip("/").split("/")) >= 2
    except ValueError:
        return False

if not url and not rss_urls:
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

rss_errors = []
rss_sources_ok = 0
rss_entries_total = 0
rss_rejected_non_avito = 0
rss_rejected_city_or_category = 0
rss_rejected_niche = 0
rss_entries_total = 0
rss_direct_links = 0
rss_rejected_other_city = 0
rss_rejected_not_listing = 0
rss_rejected_niche = 0
for rss_url in rss_urls[:100]:
    try:
        parsed = urllib.parse.urlparse(rss_url)
        if parsed.scheme != "https" or parsed.hostname not in ("www.google.com", "google.com", "www.google.ru", "google.ru") or not parsed.path.startswith("/alerts/feeds/"):
            raise ValueError("Неверный адрес Google Alerts")
        root = ET.fromstring(get_bytes(rss_url))
        entries = root.findall("{http://www.w3.org/2005/Atom}entry")
        rss_sources_ok += 1
        rss_entries_total += len(entries)
        print(f"RSS {rss_sources_ok}: {len(entries)} записей")
        for entry in entries:
            link_node = entry.find("{http://www.w3.org/2005/Atom}link")
            link = link_node.get("href", "") if link_node is not None else ""
            target = urllib.parse.urlparse(link)
            # Extract only explicit search-result URLs, never bypass site blocks.
            if target.hostname in ("www.google.com", "google.com"):
                params = urllib.parse.parse_qs(target.query)
                link = params.get("url", params.get("q", [""]))[0]
            if not is_avito_link(link):
                rss_rejected_non_avito += 1
                continue
            rss_direct_links += 1
            title = html.unescape(re.sub(r"<[^>]*>", "", entry.findtext("{http://www.w3.org/2005/Atom}title") or "")).strip()
            slug = urllib.parse.urlparse(link).path.strip("/").split("/")
            city_slugs = {
                "moskva": "Москва", "sankt-peterburg": "Санкт-Петербург",
                "novosibirsk": "Новосибирск", "ekaterinburg": "Екатеринбург",
                "kazan": "Казань", "krasnodar": "Краснодар",
                "nizhniy_novgorod": "Нижний Новгород", "chelyabinsk": "Челябинск",
                "samara": "Самара", "ufa": "Уфа", "rostov-na-donu": "Ростов-на-Дону",
                "perm": "Пермь", "voronezh": "Воронеж", "volgograd": "Волгоград",
                "omsk": "Омск"
            }
            city = city_slugs.get(slug[0], "") if slug else ""
            # RSS may include Avito catalogs, not individual listings.
            if not city:
                rss_rejected_other_city += 1
                continue
            if not re.search(r"_[0-9]{7,}/?$", urllib.parse.urlparse(link).path):
                rss_rejected_not_listing += 1
                continue
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
            if niche == "Другое":
                rss_rejected_niche += 1
                continue
            items.append({"name": title[:200] or "Объявление из Google Alerts",
                          "city": city or "Не определён", "niche": niche,
                          "url": link, "issues": "", "recommend": "",
                          "source": "Google Alerts RSS (поисковый индекс)",
                          "verification": "Не проверено: найдено в Google, а не непосредственно на Авито"})
    except (ValueError, OSError, ET.ParseError) as err:
        rss_errors.append(str(err)[:140])
        print("Ошибка чтения одной RSS-ленты: " + str(err)[:140])
if rss_urls and rss_sources_ok == 0 and not url:
    raise SystemExit("Не удалось прочитать ни одну RSS-ленту. Проверьте ссылки в GitHub Variables.")
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
                           "rss_sources_ok": rss_sources_ok, "rss_sources_total": min(len(rss_urls), 100), "rss_errors": len(rss_errors), "rss_entries_total": rss_entries_total, "rss_direct_links": rss_direct_links, "rss_rejected_other_city": rss_rejected_other_city, "rss_rejected_not_listing": rss_rejected_not_listing, "rss_rejected_niche": rss_rejected_niche, "items": all_items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Получено {len(new)} новых кандидатов. RSS: {rss_sources_ok}/{min(len(rss_urls), 100)}, записей Google: {rss_entries_total}, отклонено: не Авито {rss_rejected_non_avito}, не объявление/город {rss_rejected_city_or_category}, не ниша {rss_rejected_niche}. Актуальность Авито не утверждается.")

print(f"Диагностика: RSS записей {rss_entries_total}; подходящих строк {rss_candidate_rows}; не Авито {rss_rejected_non_avito}; не отдельные объявления {rss_rejected_not_listing}; нецелевые города {rss_rejected_city}; нецелевые ниши {rss_rejected_niche}.")
