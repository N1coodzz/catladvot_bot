"""SQLite state, durable deduplication, and alert queue."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from decimal import Decimal, InvalidOperation


def amount(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Укажи сумму числом, например 100 или 250.50.") from None
    if not result.is_finite() or result < 0 or result > 1_000_000_000:
        raise ValueError("Сумма должна быть от 0 до 1 000 000 000 USD.")
    return result


def fingerprint(row: dict) -> str:
    """v2 activity has no public row ID; combine all trade-identifying fields."""
    fields = ("proxy_wallet", "timestamp", "transaction_hash", "condition_id",
              "token_id", "side", "size", "usdc_size", "price", "outcome_index")
    normalized = {key: row.get(key) for key in fields}
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.lock = threading.RLock()
        with self.lock, self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS wallets (
                    id INTEGER PRIMARY KEY,
                    address TEXT NOT NULL UNIQUE,
                    alias TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    mode TEXT NOT NULL CHECK(mode IN ('trade', 'sum')),
                    threshold TEXT NOT NULL,
                    monitor_from_ts INTEGER NOT NULL,
                    last_ts INTEGER NOT NULL,
                    last_poll_at INTEGER,
                    last_error TEXT,
                    error_streak INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS subscriptions (
                    wallet_id INTEGER NOT NULL REFERENCES wallets(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    active_since INTEGER NOT NULL,
                    PRIMARY KEY (wallet_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS seen_events (
                    fingerprint TEXT PRIMARY KEY,
                    wallet_id INTEGER NOT NULL REFERENCES wallets(id) ON DELETE CASCADE,
                    event_ts INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS buy_accumulators (
                    wallet_id INTEGER NOT NULL REFERENCES wallets(id) ON DELETE CASCADE,
                    condition_id TEXT NOT NULL,
                    token_id TEXT NOT NULL,
                    total_usd TEXT NOT NULL,
                    count INTEGER NOT NULL,
                    first_ts INTEGER NOT NULL,
                    PRIMARY KEY (wallet_id, condition_id, token_id)
                );
                CREATE TABLE IF NOT EXISTS outbox (
                    id INTEGER PRIMARY KEY,
                    wallet_id INTEGER REFERENCES wallets(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    condition_id TEXT NOT NULL DEFAULT '',
                    token_id TEXT NOT NULL DEFAULT '',
                    payload TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    next_attempt INTEGER NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    delivered_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_seen_wallet_ts ON seen_events(wallet_id, event_ts);
                CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox(delivered_at, next_attempt, kind, id);
            """)

    def close(self):
        with self.lock:
            self.db.close()

    def wallet(self, wallet_id: int) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM wallets WHERE id=?", (wallet_id,)).fetchone()
            return dict(row) if row else None

    def by_address(self, address: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM wallets WHERE address=?", (address.lower(),)).fetchone()
            return dict(row) if row else None

    def monitored_wallets(self) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute("""
                SELECT w.* FROM wallets w WHERE EXISTS (
                    SELECT 1 FROM subscriptions s WHERE s.wallet_id=w.id AND s.enabled=1)
                ORDER BY w.id
            """)]

    def list_wallets(self, user_id: int, page: int = 0, page_size: int = 8) -> tuple[list[dict], int]:
        with self.lock:
            total = self.db.execute("SELECT count(*) FROM wallets").fetchone()[0]
            rows = self.db.execute("""
                SELECT w.*, coalesce(s.enabled,0) AS subscribed
                FROM wallets w LEFT JOIN subscriptions s
                  ON s.wallet_id=w.id AND s.user_id=?
                ORDER BY w.id DESC LIMIT ? OFFSET ?
            """, (user_id, page_size, max(0, page) * page_size)).fetchall()
            return [dict(r) for r in rows], total

    def is_subscribed(self, wallet_id: int, user_id: int) -> bool:
        with self.lock:
            row = self.db.execute("SELECT enabled FROM subscriptions WHERE wallet_id=? AND user_id=?",
                                  (wallet_id, user_id)).fetchone()
            return bool(row and row[0])

    def add_wallet(self, address: str, alias: str, mode: str, threshold: Decimal, creator: int) -> int:
        if mode not in ("trade", "sum") or (mode == "sum" and threshold == 0):
            raise ValueError("Неверный режим или порог.")
        now = int(time.time())
        with self.lock, self.db:
            cur = self.db.execute("""
                INSERT INTO wallets(address,alias,mode,threshold,monitor_from_ts,last_ts)
                VALUES (?,?,?,?,?,?)
            """, (address.lower(), alias, mode, str(threshold), now, now))
            wallet_id = cur.lastrowid
            self.db.execute("""
                INSERT INTO subscriptions(wallet_id,user_id,enabled,active_since) VALUES (?,?,1,?)
            """, (wallet_id, creator, now))
            return wallet_id

    def set_subscription(self, wallet_id: int, user_id: int, enabled: bool) -> bool:
        now = int(time.time())
        with self.lock, self.db:
            if not self.db.execute("SELECT 1 FROM wallets WHERE id=?", (wallet_id,)).fetchone():
                raise ValueError("Кошелёк уже удалён.")
            old = self.is_subscribed(wallet_id, user_id)
            if old == enabled:
                return enabled
            first_subscriber = not self.db.execute(
                "SELECT 1 FROM subscriptions WHERE wallet_id=? AND enabled=1", (wallet_id,)
            ).fetchone()
            self.db.execute("""
                INSERT INTO subscriptions(wallet_id,user_id,enabled,active_since)
                VALUES (?,?,?,?)
                ON CONFLICT(wallet_id,user_id) DO UPDATE SET
                  enabled=excluded.enabled, active_since=excluded.active_since
            """, (wallet_id, user_id, int(enabled), now))
            if enabled and first_subscriber:
                # After a full pause, never replay old trades or old partial sums.
                self.db.execute("UPDATE wallets SET monitor_from_ts=?,last_ts=? WHERE id=?",
                                (now, now, wallet_id))
                self.db.execute("DELETE FROM buy_accumulators WHERE wallet_id=?", (wallet_id,))
            if not enabled:
                self.db.execute("""UPDATE outbox SET delivered_at=-1
                                   WHERE wallet_id=? AND user_id=? AND delivered_at IS NULL""",
                                (wallet_id, user_id))
            return enabled

    def get_offset(self) -> int:
        with self.lock:
            row = self.db.execute("SELECT value FROM meta WHERE key='telegram_offset'").fetchone()
            return int(row[0]) if row else 0

    def set_offset(self, offset: int):
        with self.lock, self.db:
            self.db.execute("""INSERT INTO meta(key,value) VALUES ('telegram_offset',?)
                               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                            (str(offset),))

    def edit_wallet(self, wallet_id: int, field: str, value: str):
        if field not in ("alias", "note", "mode", "threshold"):
            raise ValueError("Недопустимое поле.")
        with self.lock, self.db:
            wallet = self.wallet(wallet_id)
            if not wallet:
                raise ValueError("Кошелёк уже удалён.")
            mode = value if field == "mode" else wallet["mode"]
            threshold = amount(value) if field == "threshold" else amount(wallet["threshold"])
            if mode not in ("trade", "sum") or (mode == "sum" and threshold == 0):
                raise ValueError("В режиме накопления порог должен быть больше нуля.")
            self.db.execute(f"UPDATE wallets SET {field}=? WHERE id=?", (value, wallet_id))
            if field in ("mode", "threshold"):
                self.db.execute("DELETE FROM buy_accumulators WHERE wallet_id=?", (wallet_id,))

    def delete_wallet(self, wallet_id: int):
        with self.lock, self.db:
            self.db.execute("DELETE FROM wallets WHERE id=?", (wallet_id,))

    def _enqueue(self, wallet_id: int, users: list[int], kind: str, payload: dict,
                 condition_id: str = "", token_id: str = ""):
        now = int(time.time())
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        for user_id in users:
            self.db.execute("""
                INSERT INTO outbox
                  (wallet_id,user_id,kind,condition_id,token_id,payload,created_at,next_attempt)
                VALUES (?,?,?,?,?,?,?,?)
            """, (wallet_id, user_id, kind, condition_id, token_id, serialized, now, now))

    def process_feed(self, wallet_id: int, rows: list[dict], allowed_users: set[int]) -> int:
        """One transaction covers dedup, accumulation, checkpoint and queued alerts."""
        processed = 0
        occurrences: dict[str, int] = {}
        with self.lock, self.db:
            wallet = self.wallet(wallet_id)
            if not wallet:
                return 0
            subscribers = [(int(s[0]), int(s[1])) for s in self.db.execute("""
                SELECT user_id, active_since FROM subscriptions
                WHERE wallet_id=? AND enabled=1
            """, (wallet_id,)) if int(s[0]) in allowed_users]
            max_ts = int(wallet["last_ts"])
            threshold = amount(wallet["threshold"])
            for row in rows:
                try:
                    ts = int(row["timestamp"])
                    side = row["side"]
                    usd = amount(row["usdc_size"])
                except (KeyError, TypeError, ValueError):
                    continue
                if ts < int(wallet["monitor_from_ts"]) or side not in ("BUY", "SELL"):
                    continue
                base = fingerprint(row)
                occurrences[base] = occurrences.get(base, 0) + 1
                fid = f"{base}:{occurrences[base]}"
                cur = self.db.execute("""
                    INSERT OR IGNORE INTO seen_events(fingerprint,wallet_id,event_ts) VALUES (?,?,?)
                """, (fid, wallet_id, ts))
                if not cur.rowcount:
                    continue
                processed += 1
                max_ts = max(max_ts, ts)
                users = [uid for uid, since in subscribers if since <= ts]
                condition = str(row.get("condition_id") or "")
                token = str(row.get("token_id") or row.get("outcome_index") or "")
                if side == "SELL":
                    self.db.execute("""DELETE FROM buy_accumulators
                                       WHERE wallet_id=? AND condition_id=? AND token_id=?""",
                                    (wallet_id, condition, token))
                    # Never show an unsent entry alert after the position's exit alert.
                    self.db.execute("""UPDATE outbox SET delivered_at=-1
                                       WHERE wallet_id=? AND condition_id=? AND token_id=?
                                         AND kind='buy' AND delivered_at IS NULL""",
                                    (wallet_id, condition, token))
                    self._enqueue(wallet_id, users, "sell",
                                  {"trade": row, "total_usd": str(usd), "count": 1},
                                  condition, token)
                elif wallet["mode"] == "trade":
                    if usd >= threshold:
                        self._enqueue(wallet_id, users, "buy",
                                      {"trade": row, "total_usd": str(usd), "count": 1},
                                      condition, token)
                else:
                    old = self.db.execute("""
                        SELECT total_usd,count,first_ts FROM buy_accumulators
                        WHERE wallet_id=? AND condition_id=? AND token_id=?
                    """, (wallet_id, condition, token)).fetchone()
                    total = (amount(old[0]) if old else Decimal(0)) + usd
                    count = (int(old[1]) if old else 0) + 1
                    first_ts = int(old[2]) if old else ts
                    if total >= threshold:
                        self._enqueue(wallet_id, users, "buy", {
                            "trade": row, "total_usd": str(total), "count": count,
                            "first_ts": first_ts,
                        }, condition, token)
                        self.db.execute("""DELETE FROM buy_accumulators
                                           WHERE wallet_id=? AND condition_id=? AND token_id=?""",
                                        (wallet_id, condition, token))
                    else:
                        self.db.execute("""
                            INSERT INTO buy_accumulators
                              (wallet_id,condition_id,token_id,total_usd,count,first_ts)
                            VALUES (?,?,?,?,?,?)
                            ON CONFLICT(wallet_id,condition_id,token_id) DO UPDATE SET
                              total_usd=excluded.total_usd,count=excluded.count,
                              first_ts=excluded.first_ts
                        """, (wallet_id, condition, token, str(total), count, first_ts))

            if wallet["error_streak"] >= 3:
                self._enqueue(wallet_id, [uid for uid, _ in subscribers], "health",
                              {"message": "✅ Связь с Polymarket восстановлена."})
            self.db.execute("""
                UPDATE wallets SET last_ts=?,last_poll_at=?,error_streak=0,last_error=NULL
                WHERE id=?
            """, (max_ts, int(time.time()), wallet_id))
        return processed

    def record_failure(self, wallet_id: int, error: str):
        with self.lock, self.db:
            wallet = self.wallet(wallet_id)
            if not wallet:
                return
            streak = int(wallet["error_streak"]) + 1
            self.db.execute("UPDATE wallets SET error_streak=?,last_error=? WHERE id=?",
                            (streak, error[:250], wallet_id))
            if streak == 3:
                users = [r[0] for r in self.db.execute(
                    "SELECT user_id FROM subscriptions WHERE wallet_id=? AND enabled=1", (wallet_id,))]
                self._enqueue(wallet_id, users, "health",
                              {"message": "⚠️ Нет связи с активностью Polymarket. Повторяем запросы; проверь /status."})

    def pending_alerts(self, allowed_users: set[int], limit: int = 30) -> list[dict]:
        with self.lock:
            rows = self.db.execute("""
                SELECT o.*, w.alias, w.address, w.note FROM outbox o
                LEFT JOIN wallets w ON w.id=o.wallet_id
                WHERE o.delivered_at IS NULL AND o.next_attempt<=?
                ORDER BY CASE o.kind WHEN 'sell' THEN 0 WHEN 'health' THEN 1 ELSE 2 END, o.id
                LIMIT ?
            """, (int(time.time()), limit)).fetchall()
            return [dict(row) for row in rows if row["user_id"] in allowed_users]

    def mark_delivered(self, outbox_id: int):
        with self.lock, self.db:
            self.db.execute("UPDATE outbox SET delivered_at=? WHERE id=?",
                            (int(time.time()), outbox_id))

    def mark_failed(self, outbox_id: int):
        with self.lock, self.db:
            row = self.db.execute("SELECT attempts FROM outbox WHERE id=?", (outbox_id,)).fetchone()
            if row:
                attempts = int(row[0]) + 1
                self.db.execute("UPDATE outbox SET attempts=?,next_attempt=? WHERE id=?",
                                (attempts, int(time.time()) + min(300, 2**min(attempts, 8)), outbox_id))

    def pending_count(self) -> int:
        with self.lock:
            return int(self.db.execute("SELECT count(*) FROM outbox WHERE delivered_at IS NULL").fetchone()[0])
