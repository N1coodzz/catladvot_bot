"""Public Polymarket APIs. No trading credentials or wallet keys are used."""

from __future__ import annotations

import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlparse
from urllib.request import Request, urlopen

GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com"
ADDRESS = re.compile(r"^0x[a-fA-F0-9]{40}$")
ADDRESS_ANYWHERE = re.compile(r"0x[a-fA-F0-9]{40}")
USER_AGENT = "Mozilla/5.0 (compatible; PolymarketWalletAlerts/1.0)"


class PolymarketError(Exception):
    pass


def get_json(base: str, path: str, params: dict | None = None) -> dict:
    url = base + path
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in range(3):
        try:
            with urlopen(req, timeout=20) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise PolymarketError(f"API ответил HTTP {exc.code}") from None
            retry_after = exc.headers.get("Retry-After", "")
            delay = float(retry_after) if retry_after.isdigit() else 2**attempt
            time.sleep(min(delay, 15))
        except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            if attempt == 2:
                raise PolymarketError(f"Не удалось получить данные API: {type(exc).__name__}") from None
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def resolve_profile(text: str) -> dict:
    """Accept a proxy wallet, /profile/0x... URL, or exact @username URL."""
    text = text.strip()
    match = ADDRESS_ANYWHERE.search(text)
    if match:
        address = match.group().lower()
    else:
        candidate = text
        if candidate.startswith("@"):
            username = candidate[1:]
        else:
            parsed = urlparse(candidate)
            if parsed.hostname not in ("polymarket.com", "www.polymarket.com"):
                raise PolymarketError("Пришли адрес 0x… или ссылку на профиль Polymarket.")
            path = unquote(parsed.path).rstrip("/")
            username = path.split("/")[-1].lstrip("@") if "/@" in path else ""
        if not username or len(username) > 80:
            raise PolymarketError("Не смог определить профиль. Пришли адрес кошелька 0x…")
        data = get_json(GAMMA, "/public-search", {
            "q": username, "search_profiles": "true", "limit_per_type": 20
        })
        exact = [p for p in data.get("profiles", [])
                 if str(p.get("name", "")).casefold() == username.casefold()]
        if len(exact) != 1:
            raise PolymarketError("Ник неоднозначен или не найден. Пришли адрес 0x… из профиля.")
        address = str(exact[0].get("proxyWallet", "")).lower()

    if not ADDRESS.fullmatch(address):
        raise PolymarketError("Неверный адрес кошелька.")
    try:
        profile = get_json(GAMMA, "/public-profile", {"address": address})
    except PolymarketError as exc:
        raise PolymarketError(f"Профиль не найден: {exc}") from None
    proxy = str(profile.get("proxyWallet", "")).lower()
    if not ADDRESS.fullmatch(proxy):
        raise PolymarketError("API не вернул публичный адрес профиля.")
    return {"address": proxy, "name": profile.get("name") or profile.get("pseudonym") or proxy[:10]}


def activity_since(address: str, start: int) -> list[dict]:
    """Read every trade in the time window, preserving the feed's sequence order."""
    params = {
        "user": address, "type": "TRADE", "start": max(1, int(start)),
        "sort_direction": "DESC", "limit": 500,
    }
    rows: list[dict] = []
    cursor = None
    for _ in range(1000):
        if cursor:
            params["cursor"] = cursor
        page = get_json(DATA, "/v2/activity", params)
        if not isinstance(page, dict) or not isinstance(page.get("data"), list):
            raise PolymarketError("API вернул неожиданный формат активности.")
        rows.extend(row for row in page["data"] if row.get("type") == "TRADE")
        pagination = page.get("pagination") or {}
        if not pagination.get("has_more"):
            return list(reversed(rows))
        new_cursor = pagination.get("next_cursor")
        if not new_cursor or new_cursor == cursor:
            raise PolymarketError("API не вернул курсор для следующей страницы.")
        cursor = new_cursor
    raise PolymarketError("Слишком много страниц активности; окно не обработано.")


def latest_activity(address: str, limit: int = 3) -> list[dict]:
    page = get_json(DATA, "/v2/activity", {"user": address, "type": "TRADE", "limit": limit})
    if not isinstance(page.get("data"), list):
        raise PolymarketError("API вернул неожиданный формат активности.")
    return page["data"]


def event_url(event_slug: str) -> str | None:
    if not event_slug or not re.fullmatch(r"[A-Za-z0-9_-]+", event_slug):
        return None
    return "https://polymarket.com/event/" + quote(event_slug, safe="-_")
