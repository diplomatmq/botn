from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id      INTEGER PRIMARY KEY,
    username     TEXT,
    first_name   TEXT,
    last_name    TEXT,
    created_at   TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS relay (
    owner_chat_id    INTEGER NOT NULL,
    owner_message_id INTEGER NOT NULL,
    user_id          INTEGER NOT NULL,
    created_at       TEXT NOT NULL,
    PRIMARY KEY (owner_chat_id, owner_message_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    direction    TEXT NOT NULL,
    chat_id      INTEGER NOT NULL,
    message_id   INTEGER NOT NULL,
    content_type TEXT NOT NULL,
    text         TEXT,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_user ON messages (user_id, id DESC);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage:
    def __init__(self, path: str):
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("storage is not connected")
        return self._conn

    async def connect(self) -> None:
        parent = Path(self._path).parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def touch_user(
        self,
        *,
        user_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
    ) -> None:
        stamp = now()
        await self.conn.execute(
            """
            INSERT INTO users (user_id, username, first_name, last_name, created_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                last_seen_at = excluded.last_seen_at
            """,
            (user_id, username, first_name, last_name, stamp, stamp),
        )
        await self.conn.commit()

    async def log_message(
        self,
        *,
        user_id: int,
        direction: str,
        chat_id: int,
        message_id: int,
        content_type: str,
        text: str | None,
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO messages (user_id, direction, chat_id, message_id, content_type, text, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, direction, chat_id, message_id, content_type, text, now()),
        )
        await self.conn.commit()

    async def link(self, owner_chat_id: int, owner_message_id: int, user_id: int) -> None:
        await self.conn.execute(
            """
            INSERT INTO relay (owner_chat_id, owner_message_id, user_id, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (owner_chat_id, owner_message_id) DO UPDATE SET user_id = excluded.user_id
            """,
            (owner_chat_id, owner_message_id, user_id, now()),
        )
        await self.conn.commit()

    async def resolve(self, owner_chat_id: int, owner_message_id: int) -> int | None:
        async with self.conn.execute(
            "SELECT user_id FROM relay WHERE owner_chat_id = ? AND owner_message_id = ?",
            (owner_chat_id, owner_message_id),
        ) as cursor:
            row = await cursor.fetchone()
        return row["user_id"] if row else None

    async def count_users(self) -> int:
        async with self.conn.execute("SELECT COUNT(*) AS total FROM users") as cursor:
            row = await cursor.fetchone()
        return row["total"]
