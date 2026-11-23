"""Безопасная диагностическая проверка уведомлений Авито в Mail.ru.

Только IMAP readonly, без загрузки тел писем, вложений или заголовков.
Ничего не публикует в GitHub Pages и не изменяет почту.
"""
import datetime as dt
import imaplib
import os
import sys

def main():
    address = os.environ.get("MAILRU_EMAIL", "").strip()
    password = os.environ.get("MAILRU_APP_PASSWORD", "")
    if not address or not password:
        print("ОШИБКА: отсутствует MAILRU_EMAIL или MAILRU_APP_PASSWORD.")
        return 1
    client = None
    try:
        print("Подключение к Mail.ru IMAP через TLS...")
        client = imaplib.IMAP4_SSL("imap.mail.ru", 993, timeout=20)
        typ, _ = client.login(address, password)
        if typ != "OK":
            print("ОШИБКА: IMAP не подтвердил вход.")
            return 1
        print("IMAP: подключение и авторизация успешны.")
        typ, _ = client.select("INBOX", readonly=True)
        if typ != "OK":
            print("ОШИБКА: не удалось открыть Входящие в режиме чтения.")
            return 1
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).strftime("%d-%b-%Y")
        # IMAP server-side search; no FETCH and no reading of message contents.
        typ, data = client.search(None, "SINCE", cutoff, "FROM", '"avito.ru"')
        if typ != "OK":
            print("ОШИБКА: поиск по отправителю не выполнен.")
            return 1
        count = len(data[0].split()) if data and data[0] else 0
        print(f"Уведомлений с avito.ru в адресе отправителя во Входящих за последние 30 дней: {count}.")
        print("Это предварительный подсчёт, а не подтверждение писем о сохранённом поиске.")
        print("Содержимое писем, темы, адреса отправителей и вложения не считывались.")
        print("Импорт объявлений пока выключен до проверки формата настоящего уведомления.")
        return 0
    except (imaplib.IMAP4.error, OSError, TimeoutError) as exc:
        # Never log server responses, as they may contain sensitive account details.
        print("ОШИБКА IMAP: подключение или вход не удались.")
        print(f"Тип ошибки: {type(exc).__name__}")
        return 1
    finally:
        if client is not None:
            try:
                client.logout()
            except (imaplib.IMAP4.error, OSError):
                pass

if __name__ == "__main__":
    sys.exit(main())
