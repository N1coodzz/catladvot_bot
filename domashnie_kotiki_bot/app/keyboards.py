from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.models import Role


def main_menu(role: Role | str | None = None) -> ReplyKeyboardMarkup:
    """Компактное главное меню с проваливанием в разделы."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Задачи"), KeyboardButton(text="📅 График")],
            [KeyboardButton(text="⭐ Баллы"), KeyboardButton(text="💞 Совместное время")],
            [KeyboardButton(text="🐾 Полезные лапки"), KeyboardButton(text="⚙️ Настройки")],
        ],
        resize_keyboard=True,
    )


def tasks_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Создать задачу"), KeyboardButton(text="📋 Мои задачи")],
            [KeyboardButton(text="🏠 Все задачи"), KeyboardButton(text="✅ Выполненные")],
            [KeyboardButton(text="💬 Обсуждения"), KeyboardButton(text="🏡 Главное меню")],
        ],
        resize_keyboard=True,
    )


def schedule_menu_keyboard(role: Role | str | None = None) -> ReplyKeyboardMarkup:
    raw = role.value if isinstance(role, Role) else role
    rows = [
        [KeyboardButton(text="➕ Добавить мой день"), KeyboardButton(text="👀 Мой график")],
        [KeyboardButton(text="👥 Общий график"), KeyboardButton(text="🖼 Красивый график")],
        [KeyboardButton(text="💞 Совместное время")],
    ]
    if raw == Role.KOT.value:
        rows.append([KeyboardButton(text="🔁 Замены"), KeyboardButton(text="🔎 Шансы для обмена")])
    rows.append([KeyboardButton(text="🏡 Главное меню")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def utilities_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🌤 Погода"), KeyboardButton(text="📊 Финансовая сводка")],
            [KeyboardButton(text="📱 SMM-лапка"), KeyboardButton(text="🧠 Слово дня")],
            [KeyboardButton(text="💬 Тема для вечера"), KeyboardButton(text="💌 Тёплое сообщение")],
            [KeyboardButton(text="🏡 Главное меню")],
        ],
        resize_keyboard=True,
    )


def cancel_back_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ Назад"), KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
    )

def role_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🐱 Я Кот", callback_data="role:kot"),
            InlineKeyboardButton(text="🐾 Я Котик", callback_data="role:kotik"),
        ]
    ])


def assignee_keyboard(current_role: Role | str | None = None) -> InlineKeyboardMarkup:
    """Кому назначить задачу.

    Создателю не показываем самого себя как отдельного ответственного:
    Кот ставит задачу Котику или обоим, Котик — Коту или обоим.
    """
    raw = current_role.value if isinstance(current_role, Role) else current_role
    rows: list[list[InlineKeyboardButton]] = []

    if raw == Role.KOT.value:
        rows.append([InlineKeyboardButton(text="🐾 Котик", callback_data="task_assignee:kotik")])
    elif raw == Role.KOTIK.value:
        rows.append([InlineKeyboardButton(text="🐱 Кот", callback_data="task_assignee:kot")])
    else:
        rows.append([
            InlineKeyboardButton(text="🐱 Кот", callback_data="task_assignee:kot"),
            InlineKeyboardButton(text="🐾 Котик", callback_data="task_assignee:kotik"),
        ])

    rows.append([InlineKeyboardButton(text="👥 Оба", callback_data="task_assignee:both")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="task_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
        [InlineKeyboardButton(text="❌ Отмена", callback_data="task_cancel")],
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
        [InlineKeyboardButton(text="❌ Отмена", callback_data="task_cancel")],
    ])


def yes_no_comment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💬 Добавить", callback_data="task_comment:yes"),
            InlineKeyboardButton(text="Пропустить", callback_data="task_comment:no"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="task_cancel")],
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
        [InlineKeyboardButton(text="🕊 Закрыть без зачёта", callback_data=f"discussion_action:close:{task_id}")],
    ])


def schedule_type_keyboard(role: Role) -> InlineKeyboardMarkup:
    if role == Role.KOT:
        buttons = [
            [InlineKeyboardButton(text="💼 Рабочая смена", callback_data="schedule_type:work_day")],
            [InlineKeyboardButton(text="🌙 Ночная смена", callback_data="schedule_type:night_shift")],
            [InlineKeyboardButton(text="💤 Выходной", callback_data="schedule_type:free")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="schedule_type:back")],
        ]
    else:
        buttons = [
            [InlineKeyboardButton(text="💼 Рабочий день", callback_data="schedule_type:work_day")],
            [InlineKeyboardButton(text="💤 Выходной", callback_data="schedule_type:free")],
            [InlineKeyboardButton(text="🌀 Ненормированный день", callback_data="schedule_type:irregular")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="schedule_type:back")],
        ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def irregular_count_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1 период", callback_data="irregular_count:1"),
            InlineKeyboardButton(text="2 периода", callback_data="irregular_count:2"),
        ],
        [
            InlineKeyboardButton(text="3 периода", callback_data="irregular_count:3"),
            InlineKeyboardButton(text="4 периода", callback_data="irregular_count:4"),
        ],
        [InlineKeyboardButton(text="✍️ Ввести число", callback_data="irregular_count:manual")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="irregular_count:back")],
    ])


def common_back_inline(callback_data: str = "common:back") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=callback_data)]])


def schedule_period_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить ещё время занятости", callback_data="schedule_period:add")],
        [InlineKeyboardButton(text="✅ Сохранить день", callback_data="schedule_period:save")],
        [
            InlineKeyboardButton(text="🧹 Очистить периоды", callback_data="schedule_period:clear"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="schedule_period:cancel"),
        ],
    ])


def schedule_result_keyboard(day_iso: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👀 Посмотреть день", callback_data=f"schedule_view:{day_iso}")],
        [InlineKeyboardButton(text="✏️ Редактировать этот день", callback_data=f"schedule_edit:{day_iso}")],
    ])


def points_period_keyboard(selected: str = "today") -> InlineKeyboardMarkup:
    def label(code: str, text: str) -> str:
        return f"✅ {text}" if selected == code else text

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=label("today", "Сегодня"), callback_data="points:today"),
            InlineKeyboardButton(text=label("week", "Неделя"), callback_data="points:week"),
        ],
        [
            InlineKeyboardButton(text=label("month", "Месяц"), callback_data="points:month"),
            InlineKeyboardButton(text=label("all", "Всё время"), callback_data="points:all"),
        ],
        [InlineKeyboardButton(text="📜 История периода", callback_data=f"points_history:{selected}")],
    ])


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
