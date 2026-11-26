"""Private, read-only validation of Avito digest links.

Reads only Avito sender mail in INBOX and Newsletters, does not write any
mail data or tokens into the repository. Makes a small number of normal HTTPS
requests to Avito, never bypasses access restrictions. Logs counts only.
"""
import datetime as dt
import imaplib
import os
import sys
import time
from email import policy
from email.parser import BytesParser
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import (
    HTTPSHandler, HTTPRedirectHandler, Request, build_opener,
)

from preview_avito_mail import Hrefs, find_folders, sender_ok, direct_listing

MAX_LINKS = 15


def safe_avito_url(value):
    try:
        p = urlsplit(unescape(value))
        return p.scheme == "https" and p.hostname in (
            "www.avito.ru", "avito.ru", "m.avito.ru"
        ) and not p.username and not p.password
    except ValueError:
        return False


class SafeAvitoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not safe_avito_url(newurl):
            raise ValueError("Redirect outside Avito blocked")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def extract_digest_links(message):
    results = {}
    for part in message.walk():
        if part.is_multipart() or part.get_content_type() != "text/html" or part.get_content_disposition() == "attachment":
            continue
        raw = part.get_payload(decode=True) or b""
        if len(raw) > 500_000:
            continue
        try:
            body = raw.decode(part.get_content_charset() or "utf-8", errors="replace")
        except LookupError:
            body = raw.decode("utf-8", errors="replace")
        parser = Hrefs()
        parser.feed(body)
        for raw_url in parser.links:
            url = unescape(raw_url)
            if not safe_avito_url(url):
                continue
            parsed = urlsplit(url)
            if not parsed.path.startswith("/autosearch/get/"):
                continue
            item_ids = parse_qs(parsed.query).get("itemId", [])
            if len(item_ids) != 1 or not (item_ids[0].isascii() and item_ids[0].isdigit() and 7 <= len(item_ids[0]) <= 15):
                continue
            results.setdefault(item_ids[0], url)
    return results


def main():
    address = os.getenv("MAILRU_EMAIL", "").strip()
    password = os.getenv("MAILRU_APP_PASSWORD", "")
    if not address or not password:
        print("Mail.ru credentials missing.")
        return 1
    client = None
    links = {}
    try:
        client = imaplib.IMAP4_SSL("imap.mail.ru", 993, timeout=20)
        client.login(address, password)
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=14)).strftime("%d-%b-%Y")
        for folder in find_folders(client):
            status, _ = client.select(folder, readonly=True)
            if status != "OK":
                continue
            status, data = client.search(None, "SINCE", since, "FROM", '"avito.ru"')
            if status != "OK":
                continue
            for message_id in (data[0].split() if data and data[0] else [])[-30:]:
                status, chunks = client.fetch(message_id, "(BODY.PEEK[])")
                if status != "OK":
                    continue
                payload = next((p[1] for p in chunks if isinstance(p, tuple) and isinstance(p[1], bytes)), None)
                if not payload or len(payload) > 1_500_000:
                    continue
                message = BytesParser(policy=policy.default).parsebytes(payload)
                if sender_ok(message):
                    links.update(extract_digest_links(message))
        print(f"Уникальных ID в рассылках: {len(links)}")
    except (imaplib.IMAP4.error, OSError, TimeoutError, ValueError):
        print("Проверка писем не удалась. Подробности скрыты.")
        return 1
    finally:
        if client is not None:
            try:
                client.logout()
            except (imaplib.IMAP4.error, OSError):
                pass

    opener = build_opener(SafeAvitoRedirect(), HTTPSHandler())
    resolved = set()
    inaccessible = 0
    other = 0
    attempted = 0
    for item_id, tracking_url in list(links.items())[:MAX_LINKS]:
        attempted += 1
        try:
            request = Request(tracking_url, headers={"User-Agent": "Mozilla/5.0 (compatible; AvitoLeadsLinkCheck/1.0)"})
            with opener.open(request, timeout=12) as response:
                final = response.geturl()
                public_url = direct_listing(final)
                if public_url and public_url.rsplit("_", 1)[-1].strip("/") == item_id:
                    resolved.add(public_url)
                else:
                    other += 1
        except (HTTPError, URLError, OSError, TimeoutError, ValueError):
            inaccessible += 1
        time.sleep(0.3)

    print(f"Проверено переходов: {attempted}")
    print(f"Получено прямых адресов объявлений: {len(resolved)}")
    print(f"Недоступных переходов: {inaccessible}")
    print(f"Переходов без подтверждённого адреса объявления: {other}")
    print("Приватные ссылки и токены не выводятся; импорт в публичную базу выключен.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
