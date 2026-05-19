from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

DDL = """
CREATE TABLE IF NOT EXISTS chat_threads (
  id TEXT PRIMARY KEY,
  title TEXT,
  created_time TEXT,
  last_edited_time TEXT,
  alive INTEGER,
  message_ids_json TEXT NOT NULL DEFAULT '[]',
  raw_json TEXT NOT NULL DEFAULT '{}',
  imported_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE TABLE IF NOT EXISTS chat_messages (
  id TEXT PRIMARY KEY,
  thread_id TEXT,
  role TEXT,
  text TEXT NOT NULL DEFAULT '',
  created_time TEXT,
  raw_json TEXT NOT NULL DEFAULT '{}',
  imported_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE VIRTUAL TABLE IF NOT EXISTS chat_messages_fts USING fts5(id UNINDEXED, thread_id UNINDEXED, role UNINDEXED, text);
"""


def get_default_chat_history_db_path() -> str:
    explicit = os.getenv("CHAT_HISTORY_DB_PATH")
    if explicit:
        return explicit
    base = os.getenv("DB_PATH", "./data/conversations.db")
    return os.path.join(os.path.dirname(os.path.abspath(base)), "chat_history.db")


class ChatHistoryStore:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or get_default_chat_history_db_path()
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        with self._conn() as conn:
            conn.executescript(DDL)
            conn.commit()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def upsert_bundle(self, bundle: dict[str, Any]) -> dict[str, int]:
        threads = bundle.get("threads", {})
        messages = bundle.get("messages", {})
        with self._conn() as conn:
            for t in threads.values():
                conn.execute(
                    """INSERT INTO chat_threads(id,title,created_time,last_edited_time,alive,message_ids_json,raw_json)
                    VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET title=excluded.title,last_edited_time=excluded.last_edited_time,alive=excluded.alive,message_ids_json=excluded.message_ids_json,raw_json=excluded.raw_json""",
                    (t["id"], t.get("title"), str(t.get("created_time") or ""), str(t.get("last_edited_time") or ""), None if t.get("alive") is None else int(bool(t.get("alive"))), json.dumps(t.get("message_ids") or []), json.dumps(t.get("raw") or {})),
                )
            for m in messages.values():
                conn.execute(
                    """INSERT INTO chat_messages(id,thread_id,role,text,created_time,raw_json)
                    VALUES(?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET thread_id=excluded.thread_id,role=excluded.role,text=excluded.text,created_time=excluded.created_time,raw_json=excluded.raw_json""",
                    (m["id"], m.get("thread_id"), m.get("role"), m.get("text") or "", str(m.get("created_time") or ""), json.dumps(m.get("raw") or {})),
                )
                conn.execute("DELETE FROM chat_messages_fts WHERE id=?", (m["id"],))
                conn.execute("INSERT INTO chat_messages_fts(id,thread_id,role,text) VALUES(?,?,?,?)", (m["id"], m.get("thread_id"), m.get("role"), m.get("text") or ""))
            conn.commit()
        return {"threads": len(threads), "messages": len(messages)}

    def list_threads(self, limit: int = 50, offset: int = 0, include_inactive: bool = False) -> list[dict[str, Any]]:
        where = "" if include_inactive else "WHERE COALESCE(alive,1) != 0"
        with self._conn() as conn:
            rows = conn.execute(f"SELECT id,title,created_time,last_edited_time,alive FROM chat_threads {where} ORDER BY last_edited_time DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
            return [dict(r) for r in rows]

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            t = conn.execute("SELECT * FROM chat_threads WHERE id=?", (thread_id,)).fetchone()
            if not t:
                return None
            msgs = conn.execute("SELECT id,thread_id,role,text,created_time FROM chat_messages WHERE thread_id=? ORDER BY created_time,id", (thread_id,)).fetchall()
        out = dict(t)
        out["message_ids"] = json.loads(out.pop("message_ids_json") or "[]")
        out["raw"] = json.loads(out.pop("raw_json") or "{}")
        out["messages"] = [dict(r) for r in msgs]
        return out

    def search(self, query: str, limit: int = 25) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT id,thread_id,role,snippet(chat_messages_fts,3,'[',']',' ... ',16) AS snippet FROM chat_messages_fts WHERE chat_messages_fts MATCH ? LIMIT ?", (query, limit)).fetchall()
            return [dict(r) for r in rows]

    def thread_to_markdown(self, thread_id: str) -> str | None:
        thread = self.get_thread(thread_id)
        if not thread:
            return None
        lines = [f"# {thread.get('title') or thread.get('id')}", "", f"Thread ID: `{thread.get('id')}`", ""]
        for msg in thread.get("messages", []):
            lines += [f"## {str(msg.get('role') or 'message').title()}", "", str(msg.get("text") or ""), ""]
        return "\n".join(lines)
