from __future__ import annotations

import random

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.keyboards import settings_keyboard, utilities_menu_keyboard
from app.services.finance import finance_summary_text
from app.services.weather import get_weather

router = Router()


@router.message(F.text.in_({"🐾 Полезные лапки", "🧰 Полезная штука"}))
async def utilities_menu(message: Message) -> None:
    await message.answer(
        "🐾 <b>Полезные лапки</b>\n\n"
        "Это уютный раздел не про контроль, а про жизнь: погода, финансы, идеи для SMM, тёплые фразы и маленькие темы для разговора.\n\n"
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


@router.message(F.text == "📊 Финансовая сводка")
async def finance_now(message: Message) -> None:
    await message.answer(await finance_summary_text())


@router.message(F.text == "📱 SMM-лапка")
async def smm_paw(message: Message) -> None:
    ideas = [
        (
            "📱 <b>SMM-лапка дня</b>\n\n"
            "Идея поста: <b>3 ошибки, из-за которых красивый профиль не продаёт</b>.\n"
            "Хук: “Почему визуал есть, а заявок нет?”\n"
            "CTA: “Сохрани и проверь свой профиль вечером”."
        ),
        (
            "📱 <b>SMM-лапка дня</b>\n\n"
            "Идея Reels: быстрый разбор “до/после” в визуале аккаунта.\n"
            "Структура: проблема → 2 правки → результат → вопрос аудитории."
        ),
        (
            "📱 <b>SMM-лапка дня</b>\n\n"
            "Идея сторис: мини-опрос “что вам сложнее — регулярность, идеи или оформление?”\n"
            "После ответа можно сделать серию полезных сторис под боли аудитории."
        ),
        (
            "📱 <b>SMM-лапка дня</b>\n\n"
            "Идея экспертного поста: <b>как понять, что контент работает</b>.\n"
            "Метрики: сохранения, ответы, переходы, заявки — не только лайки."
        ),
    ]
    await message.answer(random.choice(ideas) + "\n\n🐾 Можно взять как черновик и адаптировать под свой стиль.")


@router.message(F.text == "🧠 Слово дня")
async def word_of_day(message: Message) -> None:
    cards = [
        (
            "🧠 <b>Слово дня: эмоциональный труд</b>\n\n"
            "Это невидимая работа по поддержанию отношений, атмосферы и быта: помнить, планировать, замечать мелочи, сглаживать напряжение.\n\n"
            "🐾 Мысль для домика: забота тоже считается трудом."
        ),
        (
            "🧠 <b>Слово дня: медиаграмотность</b>\n\n"
            "Это умение проверять источники, отделять факт от мнения и не попадаться на эмоциональные манипуляции.\n\n"
            "🐾 Полезно и для новостей, и для соцсетей."
        ),
        (
            "🧠 <b>Слово дня: tone of voice</b>\n\n"
            "Это голос бренда: как он звучит, какие слова выбирает, какую эмоцию оставляет.\n\n"
            "🐾 В отношениях тоже есть tone of voice — мягкость часто решает больше, чем аргумент."
        ),
        (
            "🧠 <b>Слово дня: репрезентация</b>\n\n"
            "Это то, как разные группы людей представлены в медиа, рекламе и культуре.\n\n"
            "🐾 Хорошая репрезентация помогает людям видеть себя не как исключение, а как норму."
        ),
    ]
    await message.answer(random.choice(cards))


@router.message(F.text.in_({"💬 Тема для вечера", "💡 Идея для вечера"}))
async def evening_topic(message: Message) -> None:
    topics = [
        "💬 <b>Тема для вечера</b>\n\nЗа что сегодня хочется сказать друг другу маленькое “спасибо”?",
        "💬 <b>Тема для вечера</b>\n\nЧто на этой неделе каждый сделал для домика, но второй мог не заметить?",
        "💬 <b>Тема для вечера</b>\n\nКакой один бытовой момент можно упростить, чтобы меньше уставать?",
        "💬 <b>Тема для вечера</b>\n\nЧто было бы приятнее: тихий домашний вечер, прогулка или вкусная доставка?",
        "💬 <b>Тема для вечера</b>\n\nКакая маленькая традиция могла бы сделать вашу неделю теплее?",
    ]
    await message.answer(random.choice(topics) + "\n\nБез давления — просто мягкий повод поговорить 🐾")


@router.message(F.text == "💌 Тёплое сообщение")
async def warm_message(message: Message) -> None:
    phrases = [
        "💌 Сегодня хороший день, чтобы напомнить: “я рядом, и мы команда”.",
        "🐾 Маленькая фраза для отправки: “Спасибо, что ты есть. Даже если день сложный, с тобой теплее”.",
        "💞 Можно написать: “Давай вечером просто побудем рядом, без спешки и бытовых войн”.",
        "😽 Тёплый вариант: “Я ценю всё, что ты делаешь для нас и нашего домика”.",
        "🏡 Можно отправить: “Хочу, чтобы дома нам обоим было спокойно. Давай беречь друг друга”.",
    ]
    await message.answer(
        "💌 <b>Тёплое сообщение</b>\n\n"
        f"{random.choice(phrases)}\n\n"
        "Можно скопировать и отправить второму котику 🐾"
    )


@router.message(F.text == "🧺 Мини-чеклист")
async def old_mini_checklist(message: Message) -> None:
    # Оставлено как совместимость со старой кнопкой, если она у кого-то осталась в Telegram.
    await message.answer(await finance_summary_text())


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
