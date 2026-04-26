from __future__ import annotations

import random

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.keyboards import main_menu, settings_keyboard, utilities_menu_keyboard
from app.services.weather import get_weather

router = Router()


@router.message(F.text == "🧰 Полезная штука")
async def utilities_menu(message: Message) -> None:
    await message.answer(
        "🧰 <b>Полезная штука</b>\n\n"
        "Это маленький уютный раздел не про контроль, а про жизнь: погода, идеи для вечера, тёплые сообщения и мини-чеклисты 🐾\n\n"
        "Выбирай, что нужно котикам сейчас:",
        reply_markup=utilities_menu_keyboard(),
    )


@router.message(F.text == "⚙️ Настройки")
async def settings_menu(message: Message) -> None:
    await message.answer(
        "⚙️ <b>Настройки домашних котиков</b>\n\n"
        "Пока в MVP часть настроек редактируется через .env, но меню уже заложено для развития.",
        reply_markup=settings_keyboard(),
    )


@router.message(F.text == "🌤 Погода")
async def weather_now(message: Message) -> None:
    weather = await get_weather()
    await message.answer(
        f"🌤 <b>Погода для домашних котиков</b>\n\n"
        f"{weather['text']}\n\n"
        f"{weather['phrase']}\n\n"
        "Даже если за окном серо, внутри домика можно сделать тепло 🏡"
    )


@router.message(F.text == "💡 Идея для вечера")
async def evening_idea(message: Message) -> None:
    ideas = [
        "🍿 Домашнее кино + что-нибудь вкусное. Без сложных планов, просто рядом.",
        "🚶 Маленькая прогулка на 20–30 минут, чтобы проветрить голову и побыть вместе.",
        "☕ Чай/кофе и 15 минут без телефонов: просто поговорить о дне.",
        "🎲 Мини-игра: каждый выбирает одно маленькое желание на вечер.",
        "🏡 Уютный вечер: плед, вкусняшка и договор не обсуждать тяжёлые бытовые темы хотя бы час.",
    ]
    await message.answer(
        "💡 <b>Идея для вечера</b>\n\n"
        f"{random.choice(ideas)}\n\n"
        "Без давления — просто маленькая подсказка для котиков 💞"
    )


@router.message(F.text == "💌 Тёплое сообщение")
async def warm_message(message: Message) -> None:
    phrases = [
        "💌 Сегодня хороший день, чтобы напомнить: “я рядом, и мы команда”.",
        "🐾 Маленькая фраза для отправки: “Спасибо, что ты есть. Даже если день сложный, с тобой теплее”.",
        "💞 Можно написать: “Давай вечером просто побудем рядом, без спешки и бытовых войн”.",
        "😽 Тёплый вариант: “Я ценю всё, что ты делаешь для нас и нашего домика”.",
    ]
    await message.answer(
        "💌 <b>Тёплое сообщение</b>\n\n"
        f"{random.choice(phrases)}\n\n"
        "Можно скопировать и отправить второму котику 🐾"
    )


@router.message(F.text == "🧺 Мини-чеклист")
async def mini_checklist(message: Message) -> None:
    await message.answer(
        "🧺 <b>Мини-чеклист уюта на сегодня</b>\n\n"
        "□ 1 маленькое бытовое дело\n"
        "□ 1 тёплая фраза второму котику\n"
        "□ 1 стакан воды / чай / кофе без суеты\n"
        "□ 5 минут привести домик в порядок\n"
        "□ Не забыть, что вы не соперники, а команда 💞"
    )


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
