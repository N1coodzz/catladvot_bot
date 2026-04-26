from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any

import aiohttp

from app.utils import now_msk


_CACHE: dict[str, Any] = {"updated_at": None, "data": None}
_CACHE_TTL_MINUTES = 30

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DomashnieKotikiBot/1.0; +https://telegram.org)",
    "Accept": "application/json,text/plain,text/html,application/xml,*/*",
}


def _to_float(value: str | int | float | None) -> float | None:
    if value is None:
        return None
    cleaned = str(value).replace("\xa0", " ").replace(" ", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _fmt_money(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "н/д"
    return f"{value:,.2f}".replace(",", " ") + suffix


async def _fetch_text(url: str, params: dict | None = None) -> str | None:
    try:
        async with aiohttp.ClientSession(headers=_HEADERS) as client:
            async with client.get(url, params=params, timeout=15) as response:
                if response.status != 200:
                    return None
                return await response.text()
    except Exception:
        return None


async def _fetch_json(url: str, params: dict | None = None) -> dict | list | None:
    try:
        async with aiohttp.ClientSession(headers=_HEADERS) as client:
            async with client.get(url, params=params, timeout=15) as response:
                if response.status != 200:
                    return None
                return await response.json(content_type=None)
    except Exception:
        return None


async def get_cbr_currency() -> dict[str, float | None]:
    """Официальные курсы ЦБ РФ: USD/RUB и EUR/RUB. Без ключа."""
    text = await _fetch_text("https://www.cbr.ru/scripts/XML_daily.asp")
    result = {"USD": None, "EUR": None}
    if not text:
        return result

    try:
        root = ET.fromstring(text)
        for item in root.findall("Valute"):
            char_code = item.findtext("CharCode")
            if char_code in result:
                nominal = _to_float(item.findtext("Nominal")) or 1
                value = _to_float(item.findtext("Value"))
                result[char_code] = value / nominal if value is not None else None
    except Exception:
        pass
    return result


async def _get_binance_symbol(symbol: str) -> float | None:
    data = await _fetch_json("https://api.binance.com/api/v3/ticker/price", {"symbol": symbol})
    if isinstance(data, dict):
        return _to_float(data.get("price"))
    return None


async def _get_coingecko_crypto() -> dict[str, float | None]:
    """Fallback для крипты: CoinGecko simple price, без ключа."""
    out = {"BTCUSDT": None, "ETHUSDT": None}
    data = await _fetch_json(
        "https://api.coingecko.com/api/v3/simple/price",
        {"ids": "bitcoin,ethereum", "vs_currencies": "usd"},
    )
    if isinstance(data, dict):
        out["BTCUSDT"] = _to_float((data.get("bitcoin") or {}).get("usd"))
        out["ETHUSDT"] = _to_float((data.get("ethereum") or {}).get("usd"))
    return out


async def _get_coinbase_spot(symbol: str) -> float | None:
    """Второй fallback для крипты: Coinbase spot price."""
    data = await _fetch_json(f"https://api.coinbase.com/v2/prices/{symbol}-USD/spot")
    if isinstance(data, dict):
        return _to_float((data.get("data") or {}).get("amount"))
    return None


async def get_crypto() -> dict[str, float | None]:
    """BTC/USDT и ETH/USDT с fallback-источниками без ключа."""
    out = {
        "BTCUSDT": await _get_binance_symbol("BTCUSDT"),
        "ETHUSDT": await _get_binance_symbol("ETHUSDT"),
    }

    if out["BTCUSDT"] is None or out["ETHUSDT"] is None:
        cg = await _get_coingecko_crypto()
        out["BTCUSDT"] = out["BTCUSDT"] or cg.get("BTCUSDT")
        out["ETHUSDT"] = out["ETHUSDT"] or cg.get("ETHUSDT")

    if out["BTCUSDT"] is None:
        out["BTCUSDT"] = await _get_coinbase_spot("BTC")
    if out["ETHUSDT"] is None:
        out["ETHUSDT"] = await _get_coinbase_spot("ETH")

    return out


async def _get_brent_stooq(symbol: str) -> float | None:
    text = await _fetch_text("https://stooq.com/q/l/", {"s": symbol, "f": "sd2t2ohlcv", "h": "", "e": "csv"})
    if not text:
        return None
    try:
        reader = csv.DictReader(io.StringIO(text))
        row = next(reader, None)
        if not row:
            return None
        for key in ("Close", "Last", "Open"):
            value = _to_float(row.get(key))
            if value and value > 0:
                return value
    except Exception:
        return None
    return None


async def _get_brent_yahoo() -> float | None:
    # Brent futures on Yahoo Finance: BZ=F. URL-кодирование через params безопасно.
    data = await _fetch_json(
        "https://query1.finance.yahoo.com/v8/finance/chart/BZ=F",
        {"range": "1d", "interval": "5m"},
    )
    try:
        result = (data or {}).get("chart", {}).get("result", [])[0]
        meta = result.get("meta", {})
        value = _to_float(meta.get("regularMarketPrice") or meta.get("previousClose"))
        if value and value > 0:
            return value
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        for item in reversed(closes):
            value = _to_float(item)
            if value and value > 0:
                return value
    except Exception:
        return None
    return None


async def get_brent() -> float | None:
    """Brent с несколькими fallback-источниками. Без ключа."""
    # Stooq иногда меняет/разводит тикеры, поэтому пробуем несколько популярных вариантов.
    for symbol in ("brn.f", "bz.f", "sc.f"):
        value = await _get_brent_stooq(symbol)
        if value:
            return value
    return await _get_brent_yahoo()


async def get_key_rate() -> float | None:
    """Ключевая ставка ЦБ РФ через публичный XML/HTML fallback."""
    today = now_msk().date()
    start = today - timedelta(days=180)
    text = await _fetch_text(
        "https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx/KeyRateXML",
        {"fromDate": start.strftime("%d/%m/%Y"), "ToDate": today.strftime("%d/%m/%Y")},
    )

    # XML + regex fallback: у ЦБ формат diffgram может отличаться по регистру тегов.
    if text:
        values: list[float] = []
        try:
            root = ET.fromstring(text)
            for elem in root.iter():
                tag = elem.tag.split("}")[-1].lower()
                if tag in {"kr", "rate", "keyrate", "key_rate"} and elem.text:
                    value = _to_float(elem.text)
                    if value is not None and 0 < value < 100:
                        values.append(value)
        except Exception:
            pass

        if not values:
            for pattern in (r"<KR>([0-9]+[,.]?[0-9]*)</KR>", r"<Rate>([0-9]+[,.]?[0-9]*)</Rate>", r"<KeyRate>([0-9]+[,.]?[0-9]*)</KeyRate>"):
                for match in re.findall(pattern, text, flags=re.IGNORECASE):
                    value = _to_float(match)
                    if value is not None and 0 < value < 100:
                        values.append(value)
        if values:
            return values[-1]

    # HTML fallback с публичной страницы ЦБ.
    html = await _fetch_text("https://www.cbr.ru/hd_base/keyrate/")
    if html:
        # Берём наиболее похожее процентное значение. Обычно на странице проценты вида 16,50.
        matches = re.findall(r"([0-9]{1,2}[,.][0-9]{1,2})\s*%", html)
        for match in matches:
            value = _to_float(match)
            if value is not None and 0 < value < 100:
                return value
    return None


async def get_finance_snapshot(force: bool = False) -> dict[str, Any]:
    now = now_msk()
    updated_at = _CACHE.get("updated_at")
    if not force and updated_at and _CACHE.get("data"):
        if now - updated_at < timedelta(minutes=_CACHE_TTL_MINUTES):
            return _CACHE["data"]

    currency = await get_cbr_currency()
    crypto = await get_crypto()
    brent = await get_brent()
    key_rate = await get_key_rate()

    data = {
        "updated_at": now,
        "usd_rub": currency.get("USD"),
        "eur_rub": currency.get("EUR"),
        "btc_usdt": crypto.get("BTCUSDT"),
        "eth_usdt": crypto.get("ETHUSDT"),
        "brent": brent,
        "key_rate": key_rate,
    }
    _CACHE["updated_at"] = now
    _CACHE["data"] = data
    return data


async def finance_summary_text(force: bool = False) -> str:
    data = await get_finance_snapshot(force=force)
    updated_at: datetime = data["updated_at"]
    missing = [
        name for name, key in [
            ("BTC", "btc_usdt"),
            ("ETH", "eth_usdt"),
            ("Brent", "brent"),
            ("ключевая ставка", "key_rate"),
        ]
        if data.get(key) is None
    ]
    source_note = ""
    if missing:
        source_note = "\n🐾 Если где-то н/д — внешний источник временно не ответил. Котики не падают, просто попробуй 🔄 обновить позже."

    lines = [
        "📊 <b>Финансовая сводка для котиков</b>",
        "",
        f"💵 USD/RUB: <b>{_fmt_money(data.get('usd_rub'), ' ₽')}</b>",
        f"💶 EUR/RUB: <b>{_fmt_money(data.get('eur_rub'), ' ₽')}</b>",
        "",
        f"₿ BTC/USD: <b>{_fmt_money(data.get('btc_usdt'), ' $')}</b>",
        f"Ξ ETH/USD: <b>{_fmt_money(data.get('eth_usdt'), ' $')}</b>",
        "",
        f"🛢 Brent: <b>{_fmt_money(data.get('brent'), ' $')}</b>",
        f"🏦 Ключевая ставка ЦБ РФ: <b>{_fmt_money(data.get('key_rate'), '%')}</b>",
        "",
        f"🕘 Обновлено: {updated_at:%d.%m.%Y %H:%M} МСК",
        source_note,
        "",
        "🐾 Это не финансовый совет — просто котики держат лапку на пульсе.",
    ]
    return "\n".join(line for line in lines if line is not None)
