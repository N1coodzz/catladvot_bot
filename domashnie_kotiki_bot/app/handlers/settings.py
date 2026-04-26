from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards import settings_keyboard
from app.services.weather import get_weather

router = Router()


@router.message(F.text == "⚙️ Настройки")
async def settings_menu(message: Message) -> None:
    await message.answer(
        "⚙️ <b>Настройки домашних котиков</b>\n\n"
        "Пока в MVP часть настроек редактируется через .env, "
        "но меню уже заложено для развития.",
        reply_markup=settings_keyboard(),
    )


@router.message(F.text == "🌤 Погода")
async def weather_now(message: Message) -> None:
    weather = await get_weather()
    await message.answer(f"{weather['text']}\n\n{weather['phrase']}")


@router.callback_query(F.data.startswith("settings:"))
async def settings_callback(callback: CallbackQuery) -> None:
    kind = callback.data.split(":", 1)[1]

    if kind == "weather_city":
        await callback.message.answer(
            "🌤 Город для погоды сейчас задаётся в .env через WEATHER_CITY.\n"
            "В следующем шаге можно добавить изменение города прямо из бота."
        )
    elif kind == "exchange":
        await callback.message.answer(
            "🔁 Подсказки по обменам включены мягко: бот не должен спамить и повторять одну дату.\n"
            "Настройки лимитов пока задаются через .env."
        )
    elif kind == "notifications":
        await callback.message.answer(
            "🔕 Уведомления в MVP:\n"
            "— утро в 06:00\n"
            "— вечерняя проверка в 20:00\n"
            "— недельный отчёт в воскресенье\n\n"
            "Точные значения можно поменять в .env."
        )

    await callback.answer()
