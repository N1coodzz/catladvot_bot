"""Polymarket wallet trade alerts in private Telegram chats.

Run with: python bot.py
The bot reads public activity only. It cannot place trades.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from polymarket import PolymarketError, activity_since, event_url, latest_activity, resolve_profile
from storage import Store, amount
from telegram_api import Telegram, TelegramError

LOG = logging.getLogger("polymarket-alert-bot")
MOSCOW = ZoneInfo("Europe/Moscow")
TX_HASH = re.compile(r"^0x[a-fA-F0-9]{64}$")


def load_env_file():
    """Allow a plain KEY=value .env when running without Docker."""
    file = Path(__file__).resolve().parent / ".env"
    if file.exists():
        for line in file.read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key in ("BOT_TOKEN", "ADMIN_IDS", "DB_PATH", "POLL_INTERVAL"):
                os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def cb(label: str, data: str) -> dict:
    return {"text": label, "callback_data": data}


def url_button(label: str, url: str) -> dict:
    return {"text": label, "url": url}


def money(value: object) -> str:
    dec = amount(value)
    if dec == 0:
        return "0"
    digits = 4 if dec < 1 else 2
    return f"{dec:,.{digits}f}".replace(",", " ")


def when(timestamp: int) -> str:
    return datetime.fromtimestamp(int(timestamp), MOSCOW).strftime("%d.%m %H:%M МСК")


def format_alert(item: dict) -> tuple[str, list[list[dict]]]:
    payload = json.loads(item["payload"])
    alias = html.escape(item.get("alias") or "Кошелёк")
    address = item.get("address") or ""
    if item["kind"] == "health":
        return f"<b>{alias}</b>\n{html.escape(payload['message'])}", []

    trade = payload["trade"]
    title = html.escape(str(trade.get("title") or "Рынок")[:300])
    outcome = html.escape(str(trade.get("outcome") or "Исход не указан")[:200])
    side = item["kind"]
    header = "🚨 <b>ПРОДАЖА</b>" if side == "sell" else "🟢 <b>ПОКУПКА</b>"
    total = money(payload["total_usd"])
    count = int(payload.get("count", 1))
    if count > 1:
        action = f"Сумма {count} покупок: <b>${total}</b>"
        action += f"\nПоследняя покупка: ${money(trade.get('usdc_size', 0))}"
    else:
        action = f"{'Продал' if side == 'sell' else 'Купил'}: <b>${total}</b>"
    try:
        price = Decimal(str(trade["price"])) * 100
        price_text = f"{price:.2f}".rstrip("0").rstrip(".") + "¢"
    except (KeyError, ValueError, TypeError):
        price_text = "—"
    text = (f"{header} · <b>{alias}</b>\n"
            f"{title}\n"
            f"Исход: <b>{outcome}</b>\n"
            f"{action}\n"
            f"Цена последней сделки: {price_text}\n"
            f"Время: {when(trade.get('timestamp', time.time()))}")
    if item.get("note"):
        text += "\nПометка: " + html.escape(str(item["note"])[:120])
    age = int(time.time()) - int(trade.get("timestamp", time.time()))
    if age > 120:
        text += f"\n⚠️ Сделка {age // 60} мин. назад — проверь текущую цену."
    if count > 1 and payload.get("first_ts"):
        text += f"\nНакопление с: {when(payload['first_ts'])}"
    keyboard = []
    market_url = event_url(str(trade.get("event_slug") or trade.get("slug") or ""))
    links = []
    if market_url:
        links.append(url_button("🎯 Рынок", market_url))
    if address:
        links.append(url_button("👤 Профиль", f"https://polymarket.com/profile/{address}"))
    if links:
        keyboard.append(links)
    tx = str(trade.get("transaction_hash") or "")
    if TX_HASH.fullmatch(tx):
        keyboard.append([url_button("🔗 Транзакция", f"https://polygonscan.com/tx/{tx}")])
    return text, keyboard


class App:
    def __init__(self, store: Store, telegram: Telegram, admins: set[int], interval: int = 15):
        self.store = store
        self.telegram = telegram
        self.admins = admins
        self.interval = interval
        self.stop = threading.Event()
        self.flows: dict[int, dict] = {}

    def _message(self, chat_id: int, text: str, keyboard=None, message_id: int | None = None):
        if message_id:
            self.telegram.edit(chat_id, message_id, text, keyboard)
        else:
            self.telegram.send(chat_id, text, keyboard)

    def main_menu(self, user_id: int, message_id: int | None = None):
        text = ("<b>Polymarket · мониторинг кошельков</b>\n"
                "Покупки — по выбранному порогу. Каждая продажа — без порога.\n"
                "Список и настройки общие, уведомления включаются лично.")
        keyboard = [[cb("📋 Кошельки", "list:0"), cb("➕ Добавить", "add")],
                    [cb("🟢 Статус", "status")]]
        self._message(user_id, text, keyboard, message_id)

    def wallet_list(self, user_id: int, page: int = 0, message_id: int | None = None):
        page = max(0, page)
        rows, total = self.store.list_wallets(user_id, page)
        if page and not rows:
            return self.wallet_list(user_id, max(0, (total - 1) // 8), message_id)
        text = f"<b>Кошельки: {total}</b>\n🟢 — уведомления включены у тебя."
        keyboard = [[cb(("🟢 " if w["subscribed"] else "⚪ ") + w["alias"][:36], f"w:{w['id']}")]
                    for w in rows]
        nav = []
        if page:
            nav.append(cb("⬅️", f"list:{page - 1}"))
        if (page + 1) * 8 < total:
            nav.append(cb("➡️", f"list:{page + 1}"))
        if nav:
            keyboard.append(nav)
        keyboard += [[cb("➕ Добавить", "add"), cb("🏠 Меню", "home")]]
        self._message(user_id, text, keyboard, message_id)

    def card(self, user_id: int, wallet_id: int, message_id: int | None = None):
        w = self.store.wallet(wallet_id)
        if not w:
            return self.wallet_list(user_id, message_id=message_id)
        enabled = self.store.is_subscribed(wallet_id, user_id)
        label = "Каждая покупка" if w["mode"] == "trade" else "Накопление покупок"
        note = html.escape(w["note"][:800]) if w["note"] else "—"
        text = (f"<b>{html.escape(w['alias'])}</b>\n"
                f"<code>{w['address']}</code>\n"
                f"Заметка: {note}\n\n"
                f"Покупки: {label} от <b>${money(w['threshold'])}</b>\n"
                "Продажи: <b>каждая, без порога</b>\n"
                f"Твои уведомления: <b>{'включены' if enabled else 'выключены'}</b>")
        keyboard = [
            [cb("🔕 Выключить мне" if enabled else "🔔 Включить мне",
                f"sub:{wallet_id}:{'off' if enabled else 'on'}")],
            [cb("⚙️ Режим покупок", f"mode:{wallet_id}"),
             cb("💵 Порог", f"threshold:{wallet_id}")],
            [cb("✏️ Название", f"alias:{wallet_id}"), cb("📝 Заметка", f"note:{wallet_id}")],
            [url_button("👤 Открыть профиль", f"https://polymarket.com/profile/{w['address']}")],
            [cb("🗑 Удалить", f"delete:{wallet_id}"), cb("⬅️ Список", "list:0")],
        ]
        self._message(user_id, text, keyboard, message_id)

    def status(self, user_id: int, message_id: int | None = None):
        wallets = self.store.monitored_wallets()
        lines = [f"<b>Мониторинг</b> · активных кошельков: {len(wallets)}",
                 f"В очереди на отправку: {self.store.pending_count()}"]
        for w in wallets[:20]:
            last = when(w["last_poll_at"]) if w["last_poll_at"] else "ожидает первого запроса"
            icon = "⚠️" if w["error_streak"] else "✅"
            lines.append(f"{icon} {html.escape(w['alias'])}: {last}")
        if len(wallets) > 20:
            lines.append(f"…ещё {len(wallets) - 20}")
        self._message(user_id, "\n".join(lines), [[cb("🏠 Меню", "home")]], message_id)

    def on_callback(self, query: dict):
        user_id = int(query.get("from", {}).get("id", 0))
        msg = query.get("message") or {}
        chat = msg.get("chat") or {}
        self.telegram.answer(str(query.get("id", "")))
        if user_id not in self.admins or chat.get("type") != "private" or chat.get("id") != user_id:
            return
        data = str(query.get("data") or "")
        mid = msg.get("message_id")
        self.flows.pop(user_id, None)
        try:
            if data == "home":
                self.main_menu(user_id, mid)
            elif data == "status":
                self.status(user_id, mid)
            elif data.startswith("list:"):
                self.wallet_list(user_id, int(data.split(":")[1]), mid)
            elif data == "add":
                self.flows[user_id] = {"step": "address"}
                self.telegram.send(user_id, "Пришли адрес 0x… или ссылку на профиль Polymarket.\n/cancel — отмена.")
            elif data.startswith("w:") or data.startswith("card:"):
                wid = int(data.split(":")[1])
                self.card(user_id, wid, None if data.startswith("card:") else mid)
            elif data.startswith("sub:"):
                _, wid, choice = data.split(":")
                if choice not in ("on", "off"):
                    return
                self.store.set_subscription(int(wid), user_id, choice == "on")
                self.card(user_id, int(wid), mid)
            elif data.startswith("mode:"):
                wid = int(data.split(":")[1])
                if self.store.wallet(wid):
                    self._message(user_id, "Выбери способ уведомлений о покупках.\n"
                                  "Продажи в обоих режимах приходят всегда.", [
                        [cb("Каждая сделка от порога", f"setmode:{wid}:trade")],
                        [cb("Сумма покупок от порога", f"setmode:{wid}:sum")],
                        [cb("⬅️ Назад", f"w:{wid}")],
                    ], mid)
            elif data.startswith("setmode:"):
                _, wid, mode = data.split(":")
                self.store.edit_wallet(int(wid), "mode", mode)
                self.card(user_id, int(wid), mid)
            elif data.startswith(("threshold:", "alias:", "note:")):
                field, wid_text = data.split(":")
                wid = int(wid_text)
                if self.store.wallet(wid):
                    self.flows[user_id] = {"step": "edit", "field": field, "wallet_id": wid}
                    prompt = {"threshold": "Введи новый общий порог в USD (например, 100).",
                              "alias": "Введи новое название кошелька.",
                              "note": "Напиши заметку. Символ «-» удалит её."}[field]
                    self.telegram.send(user_id, prompt + "\n/cancel — отмена.")
            elif data.startswith("delete:"):
                wid = int(data.split(":")[1])
                w = self.store.wallet(wid)
                if w:
                    self._message(user_id, f"Удалить <b>{html.escape(w['alias'])}</b> из общего списка?", [
                        [cb("Да, удалить", f"confirm:{wid}"), cb("Нет", f"w:{wid}")]
                    ], mid)
            elif data.startswith("confirm:"):
                wid = int(data.split(":")[1])
                self.store.delete_wallet(wid)
                self.wallet_list(user_id, message_id=mid)
        except (ValueError, TelegramError) as exc:
            self.telegram.send(user_id, html.escape(str(exc)))

    def on_message(self, msg: dict):
        chat = msg.get("chat") or {}
        sender = msg.get("from") or {}
        user_id = int(sender.get("id", 0))
        if chat.get("type") != "private" or chat.get("id") != user_id:
            return
        text = str(msg.get("text") or "").strip()
        if user_id not in self.admins:
            if text.startswith(("/start", "/id")):
                self.telegram.send(user_id, f"Твой Telegram ID: <code>{user_id}</code>\n"
                                   "Владелец бота должен добавить его в ADMIN_IDS и перезапустить бота.")
            return
        if text.startswith("/cancel"):
            self.flows.pop(user_id, None)
            self.main_menu(user_id)
        elif text.startswith(("/start", "/help")):
            self.flows.pop(user_id, None)
            self.main_menu(user_id)
        elif text.startswith("/status"):
            self.status(user_id)
        elif text.startswith("/add"):
            self.flows[user_id] = {"step": "address"}
            self.telegram.send(user_id, "Пришли адрес 0x… или ссылку на профиль.\n/cancel — отмена.")
        elif text.startswith("/id"):
            self.telegram.send(user_id, f"Твой Telegram ID: <code>{user_id}</code>")
        elif user_id in self.flows:
            self._flow_input(user_id, text)
        else:
            self.main_menu(user_id)

    def _flow_input(self, user_id: int, text: str):
        flow = self.flows[user_id]
        try:
            if flow["step"] == "address":
                profile = resolve_profile(text)
                existing = self.store.by_address(profile["address"])
                if existing:
                    self.flows.pop(user_id, None)
                    self.telegram.send(user_id, "Этот кошелёк уже в общем списке.")
                    self.card(user_id, existing["id"])
                    return
                flow.update(step="alias", address=profile["address"], default_name=profile["name"])
                self.telegram.send(user_id, "Как назовём кошелёк? Например, kentiyk_tennis.\n"
                                   f"Имя профиля: <b>{html.escape(profile['name'])}</b>\n"
                                   "/cancel — отмена.")
            elif flow["step"] == "alias":
                if not text or len(text) > 80 or text.startswith("/"):
                    raise ValueError("Название должно быть от 1 до 80 символов.")
                flow.update(step="mode", alias=text)
                self.telegram.send(user_id, "Как считать порог покупок?", [
                    [cb("Каждая сделка", "newmode:trade")],
                    [cb("Сумма покупок исхода", "newmode:sum")],
                ])
            elif flow["step"] == "amount":
                threshold = amount(text.replace(" ", "").replace(",", "."))
                if flow["mode"] == "sum" and threshold == 0:
                    raise ValueError("Для накопления порог должен быть больше нуля.")
                wid = self.store.add_wallet(flow["address"], flow["alias"], flow["mode"],
                                            threshold, user_id)
                self.flows.pop(user_id, None)
                self.telegram.send(user_id, "Кошелёк добавлен. Твои уведомления включены; "
                                   "друг сможет включить свои в карточке кошелька.")
                self.card(user_id, wid)
            elif flow["step"] == "edit":
                field = flow["field"]
                if field == "threshold":
                    value = str(amount(text.replace(" ", "").replace(",", ".")))
                elif field == "alias":
                    if not text or len(text) > 80 or text.startswith("/"):
                        raise ValueError("Название должно быть от 1 до 80 символов.")
                    value = text
                else:
                    if len(text) > 800:
                        raise ValueError("Заметка должна быть короче 800 символов.")
                    value = "" if text == "-" else text
                self.store.edit_wallet(flow["wallet_id"], field, value)
                self.flows.pop(user_id, None)
                self.card(user_id, flow["wallet_id"])
        except (PolymarketError, ValueError) as exc:
            self.telegram.send(user_id, html.escape(str(exc)) + "\nПопробуй ещё раз или /cancel.")

    def handle_update(self, update: dict):
        if "callback_query" in update:
            query = update["callback_query"]
            user_id = int(query.get("from", {}).get("id", 0))
            data = str(query.get("data") or "")
            chat = (query.get("message") or {}).get("chat") or {}
            if (data.startswith("newmode:") and user_id in self.admins
                    and chat.get("type") == "private" and chat.get("id") == user_id):
                self.telegram.answer(str(query.get("id", "")))
                flow = self.flows.get(user_id)
                if flow and flow.get("step") == "mode":
                    mode = data.split(":", 1)[1]
                    if mode in ("trade", "sum"):
                        flow.update(step="amount", mode=mode)
                        self.telegram.send(user_id, "Введи порог в USD, например 100 или 500.\n"
                                           "/cancel — отмена.")
                return
            self.on_callback(query)
        elif "message" in update:
            self.on_message(update["message"])

    def monitor_one(self, wallet: dict):
        wid = wallet["id"]
        try:
            start = max(wallet["monitor_from_ts"], wallet["last_ts"] - 300)
            rows = activity_since(wallet["address"], start)
            count = self.store.process_feed(wid, rows, self.admins)
            if count:
                LOG.info("wallet=%s new_trades=%s", wid, count)
        except (PolymarketError, OSError, ValueError) as exc:
            LOG.warning("wallet=%s poll failed: %s", wid, exc)
            self.store.record_failure(wid, str(exc))

    def monitor_loop(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            while not self.stop.is_set():
                started = time.monotonic()
                wallets = self.store.monitored_wallets()
                futures = [executor.submit(self.monitor_one, w) for w in wallets]
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception:
                        LOG.exception("Unexpected monitor error")
                self.stop.wait(max(0, self.interval - (time.monotonic() - started)))

    def delivery_loop(self):
        while not self.stop.is_set():
            for item in self.store.pending_alerts(self.admins):
                try:
                    text, keyboard = format_alert(item)
                    self.telegram.send(item["user_id"], text, keyboard)
                    self.store.mark_delivered(item["id"])
                except TelegramError as exc:
                    LOG.warning("telegram delivery failed for queue id=%s: %s", item["id"], exc)
                    self.store.mark_failed(item["id"])
                except Exception:
                    LOG.exception("Could not format queue id=%s", item["id"])
                    self.store.mark_failed(item["id"])
            self.stop.wait(1)

    def run(self):
        # Long polling and the wallet monitor run independently.
        self.telegram.call("deleteWebhook", {"drop_pending_updates": False})
        threading.Thread(target=self.monitor_loop, daemon=True, name="monitor").start()
        threading.Thread(target=self.delivery_loop, daemon=True, name="delivery").start()
        offset = self.store.get_offset()
        LOG.info("Bot running; %s admins", len(self.admins))
        while not self.stop.is_set():
            try:
                updates = self.telegram.call("getUpdates", {
                    "offset": offset, "timeout": 20, "limit": 100,
                    "allowed_updates": ["message", "callback_query"],
                }, timeout=30)
                for update in updates:
                    try:
                        self.handle_update(update)
                    except Exception:
                        LOG.exception("Update failed, update_id=%s", update.get("update_id"))
                    offset = int(update["update_id"]) + 1
                    self.store.set_offset(offset)
            except TelegramError as exc:
                LOG.warning("getUpdates failed: %s", exc)
                self.stop.wait(max(3, min(exc.retry_after or 5, 30)))


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(threadName)s %(message)s")
    load_env_file()
    if len(sys.argv) == 3 and sys.argv[1] == "verify-wallet":
        profile = resolve_profile(sys.argv[2])
        print("Профиль:", profile["name"], profile["address"])
        trades = latest_activity(profile["address"], 3)
        for row in trades:
            print(when(row["timestamp"]), row["side"], row.get("outcome"),
                  "$" + money(row["usdc_size"]), event_url(row.get("event_slug", "")))
        return
    token = os.environ.get("BOT_TOKEN", "").strip()
    admins_raw = os.environ.get("ADMIN_IDS", "").strip()
    if not token or not admins_raw:
        sys.exit("Укажи BOT_TOKEN и ADMIN_IDS в .env. См. README.md.")
    try:
        admins = {int(x.strip()) for x in admins_raw.split(",")}
        if not admins or min(admins) <= 0:
            raise ValueError()
        interval = max(5, int(os.environ.get("POLL_INTERVAL", "15")))
    except ValueError:
        sys.exit("ADMIN_IDS: числа через запятую; POLL_INTERVAL: число секунд.")
    path = Path(os.environ.get("DB_PATH", "data/bot.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(str(path))
    app = App(store, Telegram(token), admins, interval)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: app.stop.set())
    try:
        app.run()
    finally:
        app.stop.set()
        store.close()


if __name__ == "__main__":
    main()
