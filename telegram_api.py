"""Small Telegram Bot API client using only Python's standard library."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class TelegramError(Exception):
    def __init__(self, message: str, retry_after: int = 0):
        super().__init__(message)
        self.retry_after = retry_after


class Telegram:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}/"

    def call(self, method: str, data: dict | None = None, timeout: int = 35):
        body = json.dumps(data or {}, ensure_ascii=False).encode("utf-8")
        request = Request(self.base + method, body,
                          headers={"Content-Type": "application/json; charset=utf-8"},
                          method="POST")
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.load(response)
        except HTTPError as exc:
            try:
                payload = json.loads(exc.read())
            except (ValueError, UnicodeDecodeError):
                raise TelegramError(f"Telegram HTTP {exc.code}") from None
        except (URLError, TimeoutError, ValueError) as exc:
            raise TelegramError(f"Telegram недоступен: {type(exc).__name__}") from None
        if not payload.get("ok"):
            retry = payload.get("parameters", {}).get("retry_after", 0)
            raise TelegramError(str(payload.get("description", "Ошибка Telegram")), int(retry))
        return payload.get("result")

    def send(self, chat_id: int, text: str, keyboard: list[list[dict]] | None = None):
        args = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                "disable_web_page_preview": True}
        if keyboard is not None:
            args["reply_markup"] = {"inline_keyboard": keyboard}
        return self.call("sendMessage", args)

    def edit(self, chat_id: int, message_id: int, text: str,
             keyboard: list[list[dict]] | None = None):
        args = {"chat_id": chat_id, "message_id": message_id, "text": text,
                "parse_mode": "HTML", "disable_web_page_preview": True}
        if keyboard is not None:
            args["reply_markup"] = {"inline_keyboard": keyboard}
        try:
            return self.call("editMessageText", args)
        except TelegramError as exc:
            if "message is not modified" in str(exc).lower():
                return None
            return self.send(chat_id, text, keyboard)

    def answer(self, query_id: str, text: str = ""):
        try:
            self.call("answerCallbackQuery", {"callback_query_id": query_id, "text": text})
        except TelegramError:
            pass
