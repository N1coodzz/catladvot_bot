from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.models import Role


def main_menu() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="➕ Создать задачу"), KeyboardButton(text="📋 Мои задачи")],
        [KeyboardButton(text="🏠 Все задачи"), KeyboardButton(text="✅ Выполненные")],
        [KeyboardButton(text="⭐ Баллы"), KeyboardButton(text="📅 График")],
        [KeyboardButton(text="🔁 Замены"), KeyboardButton(text="💞 Совместное время")],
        [KeyboardButton(text="🔁 Возможные обмены"), KeyboardButton(text="💬 Обсуждения")],
        [KeyboardButton(text="🌤 Погода"), KeyboardButton(text="⚙️ Настройки")],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def role_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🐱 Я Кот", callback_data="role:kot"),
            InlineKeyboardButton(text="🐾 Я Котик", callback_data="role:kotik"),
        ]
    ])


def assignee_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🐱 Кот", callback_data="task_assignee:kot"),
            InlineKeyboardButton(text="🐾 Котик", callback_data="task_assignee:kotik"),
        ],
        [InlineKeyboardButton(text="👥 Оба", callback_data="task_assignee:both")],
    ])


def points_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1 ⭐", callback_data="task_points:1"),
            InlineKeyboardButton(text="3 ⭐", callback_data="task_points:3"),
            InlineKeyboardButton(text="5 ⭐", callback_data="task_points:5"),
        ],
        [
            InlineKeyboardButton(text="10 ⭐", callback_data="task_points:10"),
            InlineKeyboardButton(text="✍️ Ввести вручную", callback_data="task_points:manual"),
        ],
    ])


def deadline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Сегодня", callback_data="task_deadline:today"),
            InlineKeyboardButton(text="Завтра", callback_data="task_deadline:tomorrow"),
        ],
        [
            InlineKeyboardButton(text="На этой неделе", callback_data="task_deadline:week"),
            InlineKeyboardButton(text="Без срока", callback_data="task_deadline:none"),
        ],
        [InlineKeyboardButton(text="✍️ Ввести дату", callback_data="task_deadline:manual")],
    ])


def yes_no_comment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💬 Добавить", callback_data="task_comment:yes"),
            InlineKeyboardButton(text="Пропустить", callback_data="task_comment:no"),
        ]
    ])


def task_actions_keyboard(task_id: int, status: str = "") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 В работу", callback_data=f"task_action:progress:{task_id}"),
            InlineKeyboardButton(text="✅ Выполнено", callback_data=f"task_action:done:{task_id}"),
        ],
        [
            InlineKeyboardButton(text="💬 Обсудить", callback_data=f"task_action:discuss:{task_id}"),
            InlineKeyboardButton(text="🕊 Отменить", callback_data=f"task_action:cancel:{task_id}"),
        ],
    ])


def task_review_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, всё супер", callback_data=f"task_review:count:{task_id}")],
        [
            InlineKeyboardButton(text="💬 Обсудить задачу", callback_data=f"task_review:discuss:{task_id}"),
            InlineKeyboardButton(text="🔄 Вернуть на доработку", callback_data=f"task_review:rework:{task_id}"),
        ],
    ])


def discussion_reason_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Нужно чуть доработать", callback_data=f"discuss_reason:rework:{task_id}")],
        [InlineKeyboardButton(text="⭐ Обсудить баллы", callback_data=f"discuss_reason:points:{task_id}")],
        [InlineKeyboardButton(text="❓ Есть вопрос", callback_data=f"discuss_reason:question:{task_id}")],
        [InlineKeyboardButton(text="🕊 Задача уже неактуальна", callback_data=f"discuss_reason:cancel:{task_id}")],
        [InlineKeyboardButton(text="💬 Написать комментарий", callback_data=f"discuss_reason:comment:{task_id}")],
    ])


def discussion_actions_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Засчитать", callback_data=f"discussion_action:count:{task_id}"),
            InlineKeyboardButton(text="🔄 Доработать", callback_data=f"discussion_action:rework:{task_id}"),
        ],
        [
            InlineKeyboardButton(text="⭐ Изменить баллы", callback_data=f"discussion_action:points:{task_id}"),
            InlineKeyboardButton(text="💬 Ответить", callback_data=f"discussion_action:reply:{task_id}"),
        ],
        [InlineKeyboardButton(text="🕊 Закрыть обсуждение", callback_data=f"discussion_action:close:{task_id}")],
    ])


def schedule_type_keyboard(role: Role) -> InlineKeyboardMarkup:
    if role == Role.KOT:
        buttons = [
            [InlineKeyboardButton(text="💼 Дневная смена", callback_data="schedule_type:day_shift")],
            [InlineKeyboardButton(text="🌙 Ночная смена", callback_data="schedule_type:night_shift")],
            [InlineKeyboardButton(text="🕐 Смена по времени", callback_data="schedule_type:custom_shift")],
            [InlineKeyboardButton(text="💤 Выходной", callback_data="schedule_type:free")],
            [InlineKeyboardButton(text="🔁 Замена", callback_data="schedule_type:replacement")],
        ]
    else:
        buttons = [
            [InlineKeyboardButton(text="💼 Рабочий день", callback_data="schedule_type:work_day")],
            [InlineKeyboardButton(text="💤 Выходной", callback_data="schedule_type:free")],
            [InlineKeyboardButton(text="🕑 Свободна после 14:00", callback_data="schedule_type:free_after_14")],
            [InlineKeyboardButton(text="🌆 Занята до 19:00", callback_data="schedule_type:busy_until_19")],
            [InlineKeyboardButton(text="🌀 Ненормированный день", callback_data="schedule_type:irregular")],
            [InlineKeyboardButton(text="✍️ Свой вариант", callback_data="schedule_type:custom_shift")],
        ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def exchange_keyboard(suggestion_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 Попробую узнать", callback_data=f"exchange:will_check:{suggestion_id}")],
        [
            InlineKeyboardButton(text="🐾 Пока не трогаем", callback_data=f"exchange:not_now:{suggestion_id}"),
            InlineKeyboardButton(text="💤 Не предлагать по этой дате", callback_data=f"exchange:ignore:{suggestion_id}"),
        ],
        [InlineKeyboardButton(text="⚙️ Настройки подсказок", callback_data="settings:exchange")],
    ])


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌤 Город погоды", callback_data="settings:weather_city")],
        [InlineKeyboardButton(text="🔁 Подсказки по обменам", callback_data="settings:exchange")],
        [InlineKeyboardButton(text="🔕 Уведомления", callback_data="settings:notifications")],
    ])
