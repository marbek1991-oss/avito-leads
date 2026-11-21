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

OUT = pathlib.Path("candidates.json")
url = os.environ.get("LEADS_FEED_URL", "").strip()
today = dt.datetime.now(dt.timezone.utc).isoformat()

def is_avito_link(value):
    try:
        p = urllib.parse.urlparse(str(value))
        return p.scheme == "https" and (p.hostname == "avito.ru" or (p.hostname or "").endswith(".avito.ru")) and len(p.path.strip("/").split("/")) >= 2
    except ValueError:
        return False

if not url:
    print("Источник не подключён: задайте repository variable LEADS_FEED_URL. Не создаём вымышленные объявления.")
    raise SystemExit(0)
parsed = urllib.parse.urlparse(url)
if parsed.scheme != "https" or not parsed.netloc:
    raise SystemExit("LEADS_FEED_URL должен быть HTTPS-адресом разрешённого JSON-источника")
req = urllib.request.Request(url, headers={"User-Agent": "AvitoLeadsFeedImporter/1.0", "Accept": "application/json"})
with urllib.request.urlopen(req, timeout=25) as response:
    data = response.read(2_000_001)
if len(data) > 2_000_000:
    raise SystemExit("Слишком большой источник данных")
feed = json.loads(data)
items = feed.get("items", []) if isinstance(feed, dict) else feed
if not isinstance(items, list):
    raise SystemExit("Ожидается JSON массив или объект с полем items")
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
                           "disclaimer": "Ссылки получены из внешнего источника. Актуальность объявлений не подтверждена самим импортёром.",
                           "items": all_items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Получено {len(new)} новых кандидатов от настроенного источника. Актуальность Авито не утверждается.")
