"""Приватная предварительная проверка ссылок из писем Авито.

Запускается вручную. Читает ТОЛЬКО совпавшие письма и выводит ТОЛЬКО
сводные числа, без адресов, тем, текстов и ссылок. Ничего не публикует.
"""
import base64
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
from urllib.parse import urlsplit, parse_qs, unquote

LISTING = re.compile(r"_[0-9]{7,}/?$")
URLS = re.compile(r"https://[^\s<>\"']+", re.IGNORECASE)
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

def direct_listing(value):
    try:
        p = urlsplit(value)
    except ValueError:
        return None
    if (p.scheme == "https"
        and p.hostname in ("avito.ru", "www.avito.ru", "m.avito.ru")
        and LISTING.search(p.path)):
        return p.scheme + "://" + p.hostname + p.path
    return None

def nested_listing(value):
    """Unwrap explicit URL-valued query parameters without visiting links."""
    queue = [unescape(value)]
    seen = set()
    for _ in range(12):
        if not queue:
            break
        current = queue.pop(0)
        if current in seen or len(current) > 10000:
            continue
        seen.add(current)
        found = direct_listing(current)
        if found:
            return found
        try:
            parts = urlsplit(current)
        except ValueError:
            continue
        for key, values in parse_qs(parts.query).items():
            if key.lower() in ("url", "u", "target", "redirect", "redirect_url", "link", "to", "destination", "r", "next"):
                for candidate in values[:2]:
                    decoded = unquote(unescape(candidate))
                    if decoded.startswith("https://"):
                        queue.append(decoded)
        decoded = unquote(current)
        if decoded != current and decoded.startswith("https://"):
            queue.append(decoded)
    return None

def get_listing_links(message):
    links = set()
    hyperlink_count = 0
    categories = {"avito": 0, "external": 0, "relative": 0}
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
            hyperlink_count += len(parser.links)
            for href in parser.links:
                try:
                    parsed_href = urlsplit(unescape(href))
                    host = (parsed_href.hostname or "").lower()
                    if host == "avito.ru" or host.endswith(".avito.ru"):
                        categories["avito"] += 1
                    elif parsed_href.scheme in ("http", "https"):
                        categories["external"] += 1
                    else:
                        categories["relative"] += 1
                except ValueError:
                    categories["relative"] += 1
        for value in candidates:
            value = unescape(value).rstrip('.,);]')
            found = nested_listing(value)
            if found:
                links.add(found)
    return links, hyperlink_count, categories

def decode_imap_utf7(value):
    """Decode IMAP modified UTF-7 folder names without extra dependencies."""
    def decode(match):
        encoded = match.group(1)
        if not encoded:
            return "&"
        data = encoded.replace(",", "/")
        data += "=" * (-len(data) % 4)
        return base64.b64decode(data).decode("utf-16-be", errors="replace")
    return re.sub(r"&([A-Za-z0-9+,]*)-", decode, value)

def mailbox_name(raw):
    """Extract final mailbox name from an IMAP LIST response."""
    value = raw.decode("ascii", errors="replace") if isinstance(raw, bytes) else str(raw)
    match = re.search(r'(?:"((?:[^"\\]|\\.)*)"|(\S+))\s*$', value)
    if not match:
        return ""
    name = match.group(1) if match.group(1) is not None else match.group(2)
    return decode_imap_utf7(name.replace('\\"', '"'))

def find_folders(client):
    status, lines = client.list()
    if status != "OK":
        raise imaplib.IMAP4.error("Folder listing failed")
    folders = ["INBOX"]
    for line in lines or []:
        if not line:
            continue
        name = mailbox_name(line)
        normalized = name.casefold().strip()
        if (normalized == "рассылки" or normalized.endswith("/рассылки")
            or normalized == "newsletters" or normalized.endswith("/newsletters")
            or normalized == "subscriptions" or normalized.endswith("/subscriptions")):
            if name not in folders:
                folders.append(name)
    return folders

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
        folders = find_folders(client)
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=14)).strftime("%d-%b-%Y")
        emails = 0
        candidates = set()
        hyperlinks = 0
        categories = {"avito": 0, "external": 0, "relative": 0}
        skipped = 0
        scanned = 0
        successfully_opened = 0
        for folder in folders:
            status, _ = client.select(folder, readonly=True)
            if status != "OK":
                continue
            successfully_opened += 1
            status, data = client.search(None, "SINCE", since, "FROM", '"avito.ru"')
            if status != "OK":
                print("Не удалось выполнить поиск в одной из папок.")
                return 1
            ids = (data[0].split() if data and data[0] else [])[-30:]
            scanned += len(ids)
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
                found, link_count, per_message_categories = get_listing_links(message)
                candidates.update(found)
                hyperlinks += link_count
                for category in categories:
                    categories[category] += per_message_categories[category]
        print(f"Папок проверено: {successfully_opened}")
        print(f"Папка «Рассылки» обнаружена через IMAP: {'да' if len(folders) > 1 else 'нет'}")
        print(f"Проверено потенциальных писем за 14 дней: {scanned}")
        print(f"Писем с подтверждённым доменом отправителя: {emails}")
        print(f"HTML-ссылок внутри писем (включая служебные): {hyperlinks}")
        print(f"Ссылок на домены Авито: {categories['avito']}")
        print(f"Ссылок на внешние домены (возможные перенаправления): {categories['external']}")
        print(f"Относительных ссылок: {categories['relative']}")
        print(f"Уникальных прямых ссылок с ID объявления Авито: {len(candidates)}")
        print(f"Пропущено писем: {skipped}")
        print("Предварительная проверка: актуальность объявлений и назначение писем не подтверждены.")
        print("Импорт в публичный candidates.json выключен. Личные данные не публикуются.")
        return 0
    except (imaplib.IMAP4.error, OSError, TimeoutError, ValueError):
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
