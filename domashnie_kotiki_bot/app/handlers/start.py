from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards import main_menu, role_keyboard
from app.models import Role
from app.services.users import get_user_by_tg, register_user
from app.utils import role_label

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession) -> None:
    user = await get_user_by_tg(session, message.from_user.id)
    if user:
        await message.answer(
            f"🐾 С возвращением в домик!\nТвоя роль: {role_label(user.role)}",
            reply_markup=main_menu(user.role),
        )
        return

    await message.answer(
        "🐾 <b>Привет! Я бот “Домашние котики”</b>\n\n"
        "Я помогу Коту и Котику делить быт, собирать звёздочки "
        "и находить время друг для друга 💞\n\n"
        "Выбери, кто ты:",
        reply_markup=role_keyboard(),
    )


@router.callback_query(F.data.startswith("role:"))
async def choose_role(callback: CallbackQuery, session: AsyncSession) -> None:
    raw_role = callback.data.split(":", 1)[1]
    role = Role.KOT if raw_role == "kot" else Role.KOTIK

    user, status = await register_user(session, callback.from_user.id, role)

    if status == "role_taken":
        await callback.answer("Эта роль уже занята 🐾", show_alert=True)
        return

    if status == "already_registered":
        await callback.message.answer(
            f"Ты уже зарегистрирован как {role_label(user.role)}",
            reply_markup=main_menu(user.role),
        )
        return

    await callback.message.answer(
        f"Готово! Теперь ты {role_label(role)} 🐾\n\n"
        "Добро пожаловать в домик. Тут бытовые дела превращаются в звёздочки ⭐",
        reply_markup=main_menu(role),
    )
    await callback.answer()


@router.message(Command("menu"))
async def cmd_menu(message: Message, session: AsyncSession) -> None:
    user = await get_user_by_tg(session, message.from_user.id)
    await message.answer("🏡 Главное меню домашних котиков", reply_markup=main_menu(user.role if user else None))


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "🐾 <b>Что я умею:</b>\n\n"
        "➕ создавать бытовые задачи\n"
        "⭐ начислять звёздочки\n"
        "💬 мягко обсуждать задачи\n"
        "📅 вести график\n"
        "💞 искать совместное время\n"
        "🌤 присылать погоду и доброе утро\n\n"
        "Используй кнопки меню или команду /menu."
    )
