"""Private Mail.ru -> browser-importable candidate export.

Writes an Actions artifact only: never commit it or publish to GitHub Pages.
All Mail.ru links/tokens are discarded. No outgoing Avito requests.
"""
import datetime as dt
from email import policy
from email.parser import BytesParser
from html import unescape
from html.parser import HTMLParser
import imaplib
import json
import os
from pathlib import Path
import re
import sys

from preview_avito_mail import digest_item_id, find_folders, sender_ok

OUT = Path(os.environ.get("MAIL_CANDIDATES_OUTPUT", "/tmp/avito-mail-candidates.json"))
CITIES = ["Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань", "Уфа", "Иркутск", "Ефремов", "Пермь", "Самара", "Краснодар", "Челябинск", "Ростов-на-Дону", "Нижний Новгород", "Воронеж", "Омск", "Волгоград", "Махачкала", "Грозный"]
NICHES = [
    ("Модульные дома", ["модульн", "домокомплект"]),
    ("Строительство бань", ["баня", "бани", "бань"]),
    ("Бытовки / вагончики", ["бытовк", "вагончик", "контейнер"]),
    ("Заборы / ворота", ["забор", "ворот"]),
    ("Наружная реклама", ["вывеск", "наружн", "световой короб"]),
    ("Стройматериалы", ["газоблок", "кирпич", "стройматериал"]),
    ("Строительные услуги", ["строительств", "ремонт", "кровел", "утеплен", "фасад"]),
]

class DigestParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current_id = None
        self.text = []
        self.items = {}
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            self.current_id = digest_item_id(href)
            self.text = []
    def handle_data(self, data):
        if self.current_id:
            self.text.append(data)
    def handle_endtag(self, tag):
        if tag == "a" and self.current_id:
            title = " ".join(" ".join(self.text).split())[:200]
            if title:
                self.items.setdefault(self.current_id, title)
            self.current_id = None
            self.text = []

def collect(message):
    found = {}
    for part in message.walk():
        if part.is_multipart() or part.get_content_type() != "text/html" or part.get_content_disposition() == "attachment":
            continue
        data = part.get_payload(decode=True) or b""
        if len(data) > 500_000:
            continue
        try:
            content = data.decode(part.get_content_charset() or "utf-8", errors="replace")
        except LookupError:
            content = data.decode("utf-8", errors="replace")
        p = DigestParser()
        p.feed(content)
        found.update(p.items)
    return found

def main():
    address = os.getenv("MAILRU_EMAIL", "").strip()
    password = os.getenv("MAILRU_APP_PASSWORD", "")
    if not address or not password:
        print("Mail.ru credentials missing.")
        return 1
    client = None
    candidates = {}
    try:
        client = imaplib.IMAP4_SSL("imap.mail.ru", 993, timeout=20)
        client.login(address, password)
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).strftime("%d-%b-%Y")
        for folder in find_folders(client):
            status, _ = client.select(folder, readonly=True)
            if status != "OK":
                continue
            status, results = client.search(None, "SINCE", since, "FROM", '"avito.ru"')
            if status != "OK":
                continue
            for msgid in (results[0].split() if results and results[0] else [])[-50:]:
                status, data = client.fetch(msgid, "(BODY.PEEK[])")
                if status != "OK":
                    continue
                payload = next((p[1] for p in data if isinstance(p, tuple) and isinstance(p[1], bytes)), None)
                if not payload or len(payload) > 1_500_000:
                    continue
                msg = BytesParser(policy=policy.default).parsebytes(payload)
                if sender_ok(msg):
                    candidates.update(collect(msg))
    except (imaplib.IMAP4.error, OSError, TimeoutError, ValueError):
        print("IMAP check failed. Server details suppressed.")
        return 1
    finally:
        if client:
            try:
                client.logout()
            except (imaplib.IMAP4.error, OSError):
                pass
    items = []
    for item_id, title in list(candidates.items())[:300]:
        text = title.lower()
        niche = next((name for name, terms in NICHES if any(t in text for t in terms)), "Другое")
        # City is not reliably present in anchor text; never invent.
        items.append({"itemId": item_id, "name": title, "city": "Не определён", "niche": niche,
                      "source": "Письмо Авито — сохранённый поиск", "verification": "Не проверено"})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"format": "avito-mail-candidates-v1", "created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Кандидатов в приватном файле: {len(items)}")
    print("Токены, почтовые адреса, темы и персональные ссылки НЕ сохранены.")
    print("Результат доступен только как GitHub Actions artifact; не публикуется на Pages.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
