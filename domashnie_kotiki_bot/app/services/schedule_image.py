from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ScheduleSource, User
from app.services.schedule import format_intervals, free_intervals_for_day, list_entries_for_day, shared_free_intervals
from app.services.users import get_pair
from app.utils import now_msk, role_label, schedule_status_label


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for path in candidates:
        try:
            if Path(path).exists():
                return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _entry_period(entry) -> str:
    if entry.start_at and entry.end_at:
        text = f"{entry.start_at:%H:%M}–{entry.end_at:%H:%M}"
        if entry.end_at.date() > entry.start_at.date():
            text += " +1д"
        return text
    return "весь день"


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        if draw.textbbox((0, 0), test, font=font)[2] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


async def _user_lines(session: AsyncSession, user: User, day: datetime) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    entries = await list_entries_for_day(session, user, day)
    if not entries:
        lines.append(("muted", "❓ график не заполнен"))
    else:
        for e in entries:
            repl = " · замена" if e.source_type == ScheduleSource.REPLACEMENT else ""
            lines.append(("busy" if e.start_at or e.status_type.name != "FREE" else "free", f"{schedule_status_label(e.status_type)} { _entry_period(e) }{repl}"))
            if e.comment:
                lines.append(("muted", f"💬 {e.comment[:45]}"))

    free = await free_intervals_for_day(session, user, day)
    if free is None:
        lines.append(("muted", "🕊 свободно: нужно заполнить"))
    elif free:
        lines.append(("free", f"🕊 {format_intervals(free)}"))
    else:
        lines.append(("busy", "🕊 почти нет"))
    return lines


async def create_common_schedule_image(session: AsyncSession, days: int = 7) -> str | None:
    """Создаёт презентабельную PNG-карточку общего графика на ближайшие дни."""
    kot, kotik = await get_pair(session)
    if not kot or not kotik:
        return None

    W = 1280
    header_h = 150
    row_h = 240
    H = header_h + row_h * days + 80
    bg = (248, 244, 235)
    card = (255, 255, 255)
    ink = (55, 50, 45)
    muted = (110, 110, 110)
    green = (46, 133, 88)
    red = (174, 70, 70)
    orange = (185, 115, 35)
    purple = (126, 83, 160)
    line = (226, 220, 210)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)
    f_title = _font(44, True)
    f_sub = _font(22)
    f_day = _font(30, True)
    f_head = _font(24, True)
    f_text = _font(21)
    f_small = _font(18)

    draw.rounded_rectangle((40, 35, W - 40, 120), radius=28, fill=card)
    draw.text((70, 50), "🐾 Общий график домашних котиков", font=f_title, fill=ink)
    draw.text((72, 98), "занятость, свободные окна и время вместе на ближайшие 7 дней", font=f_sub, fill=muted)

    today = datetime(now_msk().year, now_msk().month, now_msk().day)
    y = header_h
    col_day = 60
    col_kot = 245
    col_kotik = 590
    col_shared = 935
    col_w = 310

    for offset in range(days):
        day = today + timedelta(days=offset)
        y0 = y + offset * row_h
        draw.rounded_rectangle((40, y0, W - 40, y0 + row_h - 16), radius=24, fill=card)
        draw.line((220, y0 + 20, 220, y0 + row_h - 36), fill=line, width=2)
        draw.line((565, y0 + 20, 565, y0 + row_h - 36), fill=line, width=2)
        draw.line((910, y0 + 20, 910, y0 + row_h - 36), fill=line, width=2)

        dow = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][day.weekday()]
        draw.text((col_day, y0 + 25), f"{dow}", font=f_day, fill=purple)
        draw.text((col_day, y0 + 64), f"{day:%d.%m}", font=f_day, fill=ink)

        draw.text((col_kot, y0 + 24), role_label(kot.role), font=f_head, fill=ink)
        draw.text((col_kotik, y0 + 24), role_label(kotik.role), font=f_head, fill=ink)
        draw.text((col_shared, y0 + 24), "💞 Вместе", font=f_head, fill=ink)

        for x, user in ((col_kot, kot), (col_kotik, kotik)):
            yy = y0 + 60
            for kind, line_text in (await _user_lines(session, user, day))[:5]:
                color = green if kind == "free" else red if kind == "busy" else muted
                for wrapped in _wrap(draw, line_text, f_text, col_w):
                    draw.text((x, yy), wrapped, font=f_text, fill=color)
                    yy += 27

        shared = await shared_free_intervals(session, day)
        yy = y0 + 62
        if shared is None:
            shared_lines = [("muted", "❓ не хватает графика")]
        elif shared:
            shared_lines = [("free", format_intervals(shared))]
            total = round(sum(i.minutes for i in shared) / 60, 1)
            shared_lines.append(("muted", f"вместе примерно {total} ч"))
        else:
            shared_lines = [("busy", "общего окна почти нет")]
        for kind, line_text in shared_lines:
            color = green if kind == "free" else red if kind == "busy" else muted
            for wrapped in _wrap(draw, line_text, f_text, 260):
                draw.text((col_shared, yy), wrapped, font=f_text, fill=color)
                yy += 30

    footer = f"Обновлено: {now_msk():%d.%m.%Y %H:%M} МСК · Домашние котики"
    draw.text((60, H - 55), footer, font=f_small, fill=muted)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp.close()
    img.save(tmp.name, "PNG", optimize=True)
    return tmp.name
