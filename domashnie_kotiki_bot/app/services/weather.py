from __future__ import annotations

import aiohttp

from app.config import settings


def positive_weather_phrase(description: str, temp: float | None) -> str:
    desc = (description or "").lower()

    if "rain" in desc or "дожд" in desc:
        return "Дождик — отличный повод сделать день уютнее: чай, плед и чуть больше заботы друг о друге 🏡"
    if "snow" in desc or "снег" in desc:
        return "Снег добавляет немного сказки в обычный день, а котикам можно быть особенно тёплыми ❄️"
    if temp is not None and temp >= 27:
        return "Сегодня тепло, так что не забывайте воду, лёгкость в голове и мягкость друг к другу ☀️"
    if temp is not None and temp <= 0:
        return "День просит тепла, а значит можно добавить больше заботы друг о друге 😽"
    if "cloud" in desc or "облач" in desc:
        return "Небо сегодня спокойное, зато настроение можно сделать светлым самим 🐾"
    if "clear" in desc or "ясно" in desc:
        return "Солнышко уже старается сделать день хорошим, а котики могут помочь ему улыбкой ☀️"
    return "Какая бы ни была погода, день можно сделать мягким и добрым 💞"


async def get_weather(city: str | None = None) -> dict:
    city = city or settings.weather_city

    if not settings.openweather_api_key:
        return {
            "ok": False,
            "city": city,
            "text": "🌤 Погода пока без API-ключа, но день всё равно может быть хорошим.",
            "phrase": "Даже без прогноза можно взять с собой заботу и хорошее настроение 🐾",
        }

    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": city,
        "appid": settings.openweather_api_key,
        "units": "metric",
        "lang": "ru",
    }

    try:
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
    except Exception:
        return {
            "ok": False,
            "city": city,
            "text": "🌤 Погода временно спряталась.",
            "phrase": "Бот верит, что котики справятся с любым небом 🐾",
        }

    main = data.get("main", {})
    weather = (data.get("weather") or [{}])[0]
    wind = data.get("wind", {})

    temp = main.get("temp")
    feels = main.get("feels_like")
    description = weather.get("description", "погода без описания")
    wind_speed = wind.get("speed")

    text = f"🌤 Погода в {city}: {temp:+.0f}°C, {description}\n"
    if feels is not None:
        text += f"Ощущается как: {feels:+.0f}°C\n"
    if wind_speed is not None:
        text += f"Ветер: {wind_speed} м/с"

    return {
        "ok": True,
        "city": city,
        "temp": temp,
        "feels_like": feels,
        "description": description,
        "wind_speed": wind_speed,
        "text": text.strip(),
        "phrase": positive_weather_phrase(description, temp),
    }
