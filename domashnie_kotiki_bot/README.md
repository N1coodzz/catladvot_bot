# 🐾 Домашние котики — Telegram-бот для пары

MVP Telegram-бота по ТЗ:

- 🐱 роли: Кот и Котик;
- 📝 бытовые задачи без жёстких категорий;
- ✅ новая логика подтверждения задач: `Выполнено → Ждёт подтверждения → Засчитана`;
- ⭐ баллы начисляются только после подтверждения второго котика;
- 💬 мягкое обсуждение задач вместо “споров”;
- 📅 ручной график с несколькими периодами занятости в один день;
- 🌙 ночные и 12-часовые смены;
- 🔁 замены только для Кота;
- 🔎 шансы для обмена смены только для Кота;
- 👥 общий график на 7 дней;
- 💞 поиск совместного свободного времени;
- 🌤 утреннее сообщение с погодой через Open-Meteo без API-ключа;
- 📊 финансовая сводка: USD/RUB, EUR/RUB, BTC, ETH, Brent, ключевая ставка;
- 🐾 раздел “Полезные лапки”: погода, финансы, SMM-идея, слово дня, тема для вечера, тёплое сообщение;
- ⏰ плановые уведомления по Москве.

## Стек

- Python 3.11+
- aiogram 3
- SQLAlchemy async
- SQLite для MVP
- APScheduler
- aiohttp
- Open-Meteo без API-ключа
- публичные источники финансовых данных без ключей

## Быстрый запуск

1. Создай бота через BotFather и получи токен.
2. Скопируй `.env.example` в `.env`.
3. Заполни переменные:

```env
BOT_TOKEN=123456:ABC
WEATHER_CITY=Moscow
TIMEZONE=Europe/Moscow
DATABASE_URL=sqlite+aiosqlite:///./domashnie_kotiki.sqlite3
MORNING_MESSAGE_TIME=06:00
EVENING_MESSAGE_TIME=20:00
```

4. Установи зависимости:

```bash
python -m venv .venv
source .venv/bin/activate  # Linux / macOS
# .venv\Scripts\activate   # Windows

pip install -r requirements.txt
```

5. Запусти:

```bash
python -m app.main
```

## Railway

Root Directory:

```text
domashnie_kotiki_bot
```

Start Command:

```bash
python -m app.main
```

Variables:

```env
BOT_TOKEN=...
DATABASE_URL=sqlite+aiosqlite:///./domashnie_kotiki.sqlite3
WEATHER_CITY=Moscow
TIMEZONE=Europe/Moscow
MORNING_MESSAGE_TIME=06:00
EVENING_MESSAGE_TIME=20:00
```

Для постоянной SQLite-базы на Railway лучше подключить Volume и использовать:

```env
DATABASE_URL=sqlite+aiosqlite:////data/domashnie_kotiki.sqlite3
```

## Важный апдейт финальной версии

Задачи больше не засчитываются сразу после кнопки “Выполнено”. Теперь:

1. Ответственный нажимает `✅ Выполнено`.
2. Задача получает статус `⏳ Ждёт подтверждения`.
3. Второй котик получает уведомление и кнопки:
   - `✅ Да, всё супер`;
   - `💬 Обсудить задачу`;
   - `🔄 Вернуть на доработку`.
4. Баллы начисляются только после `✅ Засчитать`.
5. Повторное нажатие не дублирует баллы.
6. Если задача для `👥 Оба`, баллы при подтверждении получает и Кот, и Котик.

## После обновления

Если тестируешь на старой SQLite-базе и видишь странные старые статусы, для чистого теста можно удалить `domashnie_kotiki.sqlite3` и пройти регистрацию заново.
