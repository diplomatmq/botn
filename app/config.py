import os
from dataclasses import dataclass
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _load_env(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


@dataclass(frozen=True)
class Config:
    bot_token: str
    owner_ids: tuple[int, ...]
    db_path: str
    user_greeting: str


def _parse_ids(raw: str) -> tuple[int, ...]:
    result = []
    for chunk in raw.replace(";", ",").replace(" ", ",").split(","):
        chunk = chunk.strip()
        if chunk and chunk.lstrip("-").isdigit():
            result.append(int(chunk))
    return tuple(dict.fromkeys(result))


def load_config() -> Config:
    _load_env(ENV_FILE)

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        raise RuntimeError("BOT_TOKEN is not set")

    owner_ids = _parse_ids(os.getenv("OWNER_IDS", ""))
    if not owner_ids:
        raise RuntimeError("OWNER_IDS is not set")

    db_path = os.getenv("DB_PATH", "data/bot.db").strip() or "data/bot.db"
    greeting = os.getenv("USER_GREETING", "").strip() or (
        "Напишите сообщение — я передам его оператору, и он ответит вам здесь."
    )

    return Config(
        bot_token=bot_token,
        owner_ids=owner_ids,
        db_path=db_path,
        user_greeting=greeting,
    )
