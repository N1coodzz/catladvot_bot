from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any

import aiohttp

from app.utils import now_msk


_CACHE: dict[str, Any] = {"updated_at": None, "data": None}
_CACHE_TTL_MINUTES = 30


def _to_float(value: str | int | float | None) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def _fmt_money(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "н/д"
    return f"{value:,.2f}".replace(",", " ") + suffix


async def _fetch_text(url: str, params: dict | None = None) -> str | None:
    try:
        async with aiohttp.ClientSession() as client:
            async with client.get(url, params=params, timeout=12) as response:
                if response.status != 200:
                    return None
                return await response.text()
    except Exception:
        return None


async def _fetch_json(url: str, params: dict | None = None) -> dict | list | None:
    try:
        async with aiohttp.ClientSession() as client:
            async with client.get(url, params=params, timeout=12) as response:
                if response.status != 200:
                    return None
                return await response.json()
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


async def get_binance_crypto() -> dict[str, float | None]:
    """Публичные цены Binance Spot по BTC/USDT и ETH/USDT. Без ключа."""
    out = {"BTCUSDT": None, "ETHUSDT": None}
    for symbol in out:
        data = await _fetch_json("https://api.binance.com/api/v3/ticker/price", {"symbol": symbol})
        if isinstance(data, dict):
            out[symbol] = _to_float(data.get("price"))
    return out


async def get_brent() -> float | None:
    """Brent через публичный CSV Stooq. Если источник не ответил — вернём None."""
    text = await _fetch_text("https://stooq.com/q/l/", {"s": "brn.f", "f": "sd2t2ohlcv", "h": "", "e": "csv"})
    if not text:
        return None
    try:
        reader = csv.DictReader(io.StringIO(text))
        row = next(reader, None)
        if not row:
            return None
        close = _to_float(row.get("Close"))
        if close and close > 0:
            return close
        return _to_float(row.get("Last"))
    except Exception:
        return None


async def get_key_rate() -> float | None:
    """Ключевая ставка ЦБ РФ через публичный XML-метод. Если формат изменится — будет None."""
    today = now_msk().date()
    start = today - timedelta(days=90)
    # Сервис ЦБ обычно понимает dd/mm/YYYY.
    text = await _fetch_text(
        "https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx/KeyRateXML",
        {"fromDate": start.strftime("%d/%m/%Y"), "ToDate": today.strftime("%d/%m/%Y")},
    )
    if not text:
        return None
    try:
        root = ET.fromstring(text)
        rates: list[tuple[str, float]] = []
        for elem in root.iter():
            tag = elem.tag.split("}")[-1].lower()
            if tag in {"kr", "rate"} and elem.text:
                rate = _to_float(elem.text)
                if rate is not None:
                    # дату искать сложно из-за diffgram, поэтому просто берём порядок появления;
                    rates.append(("", rate))
        if rates:
            return rates[-1][1]
    except Exception:
        return None
    return None


async def get_finance_snapshot(force: bool = False) -> dict[str, Any]:
    now = now_msk()
    updated_at = _CACHE.get("updated_at")
    if not force and updated_at and _CACHE.get("data"):
        if now - updated_at < timedelta(minutes=_CACHE_TTL_MINUTES):
            return _CACHE["data"]

    currency = await get_cbr_currency()
    crypto = await get_binance_crypto()
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
    lines = [
        "📊 <b>Финансовая сводка для котиков</b>",
        "",
        f"💵 USD/RUB: <b>{_fmt_money(data.get('usd_rub'), ' ₽')}</b>",
        f"💶 EUR/RUB: <b>{_fmt_money(data.get('eur_rub'), ' ₽')}</b>",
        "",
        f"₿ BTC/USDT: <b>{_fmt_money(data.get('btc_usdt'), ' $')}</b>",
        f"Ξ ETH/USDT: <b>{_fmt_money(data.get('eth_usdt'), ' $')}</b>",
        "",
        f"🛢 Brent: <b>{_fmt_money(data.get('brent'), ' $')}</b>",
        f"🏦 Ключевая ставка ЦБ РФ: <b>{_fmt_money(data.get('key_rate'), '%')}</b>",
        "",
        f"🕘 Обновлено: {updated_at:%d.%m.%Y %H:%M} МСК",
        "",
        "🐾 Это не финансовый совет — просто котики держат лапку на пульсе.",
    ]
    return "\n".join(lines)
