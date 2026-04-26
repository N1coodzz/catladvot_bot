from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str
    database_url: str
    openweather_api_key: str | None
    weather_city: str
    timezone: str
    morning_message_time: str
    evening_message_time: str
    weekly_report_time: str
    task_discussion_hours: int
    exchange_suggestions_enabled: bool
    exchange_max_per_week: int
    exchange_min_hours_before_shift: int

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "да", "on"}


def get_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is empty. Create .env and set BOT_TOKEN.")

    return Settings(
        bot_token=token,
        database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./domashnie_kotiki.sqlite3"),
        openweather_api_key=os.getenv("OPENWEATHER_API_KEY") or None,
        weather_city=os.getenv("WEATHER_CITY", "Moscow"),
        timezone=os.getenv("TIMEZONE", "Europe/Moscow"),
        morning_message_time=os.getenv("MORNING_MESSAGE_TIME", "06:00"),
        evening_message_time=os.getenv("EVENING_MESSAGE_TIME", "20:00"),
        weekly_report_time=os.getenv("WEEKLY_REPORT_TIME", "19:00"),
        task_discussion_hours=int(os.getenv("TASK_DISCUSSION_HOURS", "24")),
        exchange_suggestions_enabled=_bool(os.getenv("EXCHANGE_SUGGESTIONS_ENABLED"), True),
        exchange_max_per_week=int(os.getenv("EXCHANGE_MAX_PER_WEEK", "2")),
        exchange_min_hours_before_shift=int(os.getenv("EXCHANGE_MIN_HOURS_BEFORE_SHIFT", "24")),
    )


settings = get_settings()
