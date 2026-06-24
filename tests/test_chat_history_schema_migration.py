import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from app.chat_history.store import ChatHistoryStore, MODEL_METADATA_COLUMNS


def test_store_upgrades_legacy_chat_messages_schema():
    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "chat_history.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE chat_messages (
                  id TEXT PRIMARY KEY,
                  thread_id TEXT,
                  role TEXT,
                  text TEXT NOT NULL DEFAULT '',
                  created_time TEXT,
                  raw_json TEXT NOT NULL DEFAULT '{}',
                  imported_at INTEGER NOT NULL DEFAULT 0
                );
                INSERT INTO chat_messages(id, text) VALUES ('legacy-1', 'preserve me');
                """
            )
        finally:
            conn.close()

        ChatHistoryStore(str(db_path))

        conn = sqlite3.connect(db_path)
        try:
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(chat_messages)").fetchall()
            }
            legacy_text = conn.execute(
                "SELECT text FROM chat_messages WHERE id = 'legacy-1'"
            ).fetchone()[0]
        finally:
            conn.close()

        assert set(MODEL_METADATA_COLUMNS).issubset(columns)
        assert legacy_text == "preserve me"


def test_list_threads_accepts_notion_markdown_chat_type():
    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "chat_history.db"
        store = ChatHistoryStore(str(db_path))
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO chat_threads(id, raw_json) VALUES (?, ?)",
                ("visible-chat", '{"type":"markdownChat"}'),
            )
            conn.commit()
        finally:
            conn.close()

        thread_ids = {item["id"] for item in store.list_threads()}
        assert "visible-chat" in thread_ids
