"""Приватная предварительная проверка ссылок из писем Авито.

Запускается вручную. Читает ТОЛЬКО совпавшие письма и выводит ТОЛЬКО
сводные числа, без адресов, тем, текстов и ссылок. Ничего не публикует.
"""
import datetime as dt
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from html import unescape
from html.parser import HTMLParser
import imaplib
import os
import re
import sys
from urllib.parse import urlsplit

LISTING = re.compile(r"_[0-9]{7,}/?$")
URLS = re.compile(r"https://[^\\s<>\"']+", re.IGNORECASE)
ALLOWED_SENDERS = ("avito.ru",)

class Hrefs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.extend(value for key, value in attrs if key == "href" and value)

def sender_ok(message):
    sender = parseaddr(str(message.get("From", "")))[1].lower()
    domain = sender.rpartition("@")[2]
    return domain in ALLOWED_SENDERS or domain.endswith(".avito.ru")

def get_listing_links(message):
    links = set()
    for part in message.walk():
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        if part.get_content_type() not in ("text/plain", "text/html"):
            continue
        raw = part.get_payload(decode=True) or b""
        if len(raw) > 500_000:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            body = raw.decode(charset, errors="replace")
        except LookupError:
            body = raw.decode("utf-8", errors="replace")
        candidates = URLS.findall(body)
        if part.get_content_type() == "text/html":
            parser = Hrefs()
            parser.feed(body)
            candidates += parser.links
        for value in candidates:
            value = unescape(value).rstrip('.,);]')
            try:
                parsed = urlsplit(value)
            except ValueError:
                continue
            if (parsed.scheme == "https"
                and parsed.hostname in ("avito.ru", "www.avito.ru", "m.avito.ru")
                and LISTING.search(parsed.path)):
                links.add(parsed.scheme + "://" + parsed.hostname + parsed.path)
    return links

def main():
    address = os.getenv("MAILRU_EMAIL", "").strip()
    password = os.getenv("MAILRU_APP_PASSWORD", "")
    if not address or not password:
        print("Не настроены защищённые данные Mail.ru.")
        return 1
    client = None
    try:
        client = imaplib.IMAP4_SSL("imap.mail.ru", 993, timeout=20)
        client.login(address, password)
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            print("Не удалось выбрать папку Входящие.")
            return 1
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=14)).strftime("%d-%b-%Y")
        status, data = client.search(None, "SINCE", since, "FROM", '"avito.ru"')
        if status != "OK":
            print("Не удалось выполнить поиск.")
            return 1
        ids = (data[0].split() if data and data[0] else [])[-30:]
        emails = 0
        candidates = set()
        skipped = 0
        for message_id in ids:
            status, result = client.fetch(message_id, "(BODY.PEEK[])")
            if status != "OK":
                skipped += 1
                continue
            payload = next((part[1] for part in result if isinstance(part, tuple) and isinstance(part[1], bytes)), None)
            if not payload or len(payload) > 1_500_000:
                skipped += 1
                continue
            message = BytesParser(policy=policy.default).parsebytes(payload)
            if not sender_ok(message):
                skipped += 1
                continue
            emails += 1
            candidates.update(get_listing_links(message))
        print(f"Проверено потенциальных писем за 14 дней: {len(ids)}")
        print(f"Писем с подтверждённым доменом отправителя: {emails}")
        print(f"Уникальных прямых ссылок с ID объявления Авито: {len(candidates)}")
        print(f"Пропущено писем: {skipped}")
        print("Предварительная проверка: актуальность объявлений и назначение писем не подтверждены.")
        print("Импорт в публичный candidates.json выключен. Личные данные не публикуются.")
        return 0
    except (imaplib.IMAP4.error, OSError, TimeoutError):
        print("Ошибка IMAP при предварительной проверке; детали сервера скрыты.")
        return 1
    finally:
        if client is not None:
            try:
                client.logout()
            except (imaplib.IMAP4.error, OSError):
                pass

if __name__ == "__main__":
    sys.exit(main())
