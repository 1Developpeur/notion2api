from __future__ import annotations

import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENV_FILE = REPO / ".env"
DEFAULT_DB = REPO / "data" / "chat_history.db"


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def resolve_chat_history_db(env: dict[str, str]) -> Path:
    explicit = env.get("CHAT_HISTORY_DB_PATH")
    if explicit:
        return Path(explicit)
    main_db = env.get("DB_PATH")
    if main_db:
        return Path(main_db).expanduser().resolve().parent / "chat_history.db"
    return DEFAULT_DB


def main() -> int:
    env = parse_env_file(ENV_FILE)
    db_path = resolve_chat_history_db(env)
    print(f"chat_history_db={db_path}")

    if not db_path.exists():
        print("chat_history.db does not exist yet; no migration needed until history is imported.")
        return 0

    wanted = [
        "requested_model",
        "notion_requested_model",
        "actual_model",
        "model_provider",
    ]

    with sqlite3.connect(str(db_path)) as conn:
        table_row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chat_messages'"
        ).fetchone()
        if not table_row:
            print("chat_messages table does not exist yet; no migration needed until history is imported.")
            return 0

        cols = {row[1] for row in conn.execute("PRAGMA table_info(chat_messages)").fetchall()}
        added: list[str] = []
        for name in wanted:
            if name not in cols:
                conn.execute("ALTER TABLE chat_messages ADD COLUMN " + name + " TEXT")
                added.append(name)
        conn.commit()

        final_cols = [row[1] for row in conn.execute("PRAGMA table_info(chat_messages)").fetchall()]

    if added:
        print("added=" + ",".join(added))
    else:
        print("added=<none>")
    print("model_columns=" + ",".join([c for c in final_cols if c in wanted]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
