from __future__ import annotations

import aiohttp

from app.config import settings


WEATHER_CODE_RU = {
    0: "ясно",
    1: "преимущественно ясно",
    2: "переменная облачность",
    3: "пасмурно",
    45: "туман",
    48: "изморозь и туман",
    51: "лёгкая морось",
    53: "морось",
    55: "сильная морось",
    56: "лёгкая ледяная морось",
    57: "ледяная морось",
    61: "небольшой дождь",
    63: "дождь",
    65: "сильный дождь",
    66: "лёгкий ледяной дождь",
    67: "ледяной дождь",
    71: "небольшой снег",
    73: "снег",
    75: "сильный снег",
    77: "снежные зёрна",
    80: "небольшой ливень",
    81: "ливень",
    82: "сильный ливень",
    85: "небольшой снегопад",
    86: "сильный снегопад",
    95: "гроза",
    96: "гроза с градом",
    99: "сильная гроза с градом",
}


async def _geocode_city(city: str) -> dict | None:
    """Ищем координаты города через бесплатный Open-Meteo Geocoding API."""
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {
        "name": city,
        "count": 1,
        "language": "ru",
        "format": "json",
    }

    async with aiohttp.ClientSession() as client:
        async with client.get(url, params=params, timeout=10) as response:
            if response.status != 200:
                return None
            data = await response.json()

    results = data.get("results") or []
    if not results:
        return None

    result = results[0]
    return {
        "name": result.get("name") or city,
        "country": result.get("country"),
        "latitude": result.get("latitude"),
        "longitude": result.get("longitude"),
    }


def _description_from_code(code: int | None) -> str:
    if code is None:
        return "погода без описания"
    return WEATHER_CODE_RU.get(int(code), f"погодный код {code}")


def positive_weather_phrase(description: str, temp: float | None) -> str:
    desc = (description or "").lower()

    if "дожд" in desc or "ливень" in desc or "морось" in desc:
        return "Дождик — отличный повод сделать день уютнее: чай, плед и чуть больше заботы друг о друге 🏡"
    if "снег" in desc:
        return "Снег добавляет немного сказки в обычный день, а котикам можно быть особенно тёплыми ❄️"
    if "гроза" in desc:
        return "Гроза звучит серьёзно, но дома можно устроить маленький островок спокойствия и заботы 💞"
    if temp is not None and temp >= 27:
        return "Сегодня тепло, так что не забывайте воду, лёгкость в голове и мягкость друг к другу ☀️"
    if temp is not None and temp <= 0:
        return "День просит тепла, а значит можно добавить больше заботы друг о друге 😽"
    if "пасмур" in desc or "облач" in desc or "туман" in desc:
        return "Небо сегодня спокойное, зато настроение можно сделать светлым самим 🐾"
    if "ясно" in desc:
        return "Солнышко уже старается сделать день хорошим, а котики могут помочь ему улыбкой ☀️"
    return "Какая бы ни была погода, день можно сделать мягким и добрым 💞"


async def get_weather(city: str | None = None) -> dict:
    """
    Получаем погоду через Open-Meteo.
    Денег и API-ключа не нужно: сервис бесплатный для некоммерческого использования.
    """
    city = city or settings.weather_city

    try:
        location = await _geocode_city(city)

        # Фолбэк на Москву, если город не найден или API геокодинга временно не ответил.
        if not location:
            location = {
                "name": "Москва",
                "country": "Россия",
                "latitude": 55.7558,
                "longitude": 37.6173,
            }

        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "current": ",".join([
                "temperature_2m",
                "apparent_temperature",
                "precipitation",
                "rain",
                "showers",
                "snowfall",
                "weather_code",
                "wind_speed_10m",
            ]),
            "timezone": settings.timezone,
            "forecast_days": 1,
        }

        async with aiohttp.ClientSession() as client:
            async with client.get(url, params=params, timeout=10) as response:
                if response.status != 200:
                    return {
                        "ok": False,
                        "city": city,
                        "text": "🌤 Погоду сейчас не получилось узнать.",
                        "phrase": "Но день всё равно можно сделать тёплым внутри 💞",
                    }
                data = await response.json()

        current = data.get("current") or {}
        temp = current.get("temperature_2m")
        feels = current.get("apparent_temperature")
        code = current.get("weather_code")
        description = _description_from_code(code)
        wind_speed = current.get("wind_speed_10m")

        display_city = location.get("name") or city
        text = f"🌤 Погода в {display_city}: {temp:+.0f}°C, {description}\n" if temp is not None else f"🌤 Погода в {display_city}: {description}\n"
        if feels is not None:
            text += f"Ощущается как: {feels:+.0f}°C\n"
        if wind_speed is not None:
            text += f"Ветер: {wind_speed:.0f} км/ч"

        return {
            "ok": True,
            "city": display_city,
            "temp": temp,
            "feels_like": feels,
            "description": description,
            "wind_speed": wind_speed,
            "text": text.strip(),
            "phrase": positive_weather_phrase(description, temp),
        }

    except Exception:
        return {
            "ok": False,
            "city": city,
            "text": "🌤 Погода временно спряталась.",
            "phrase": "Бот верит, что котики справятся с любым небом 🐾",
        }
