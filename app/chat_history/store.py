from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

from app.chat_history.extractor import describe_thread_record

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


def _quote_fts_phrase(query: str) -> str:
    return '"' + query.replace('"', '""') + '"'


def _preview(text: str | None, limit: int = 180) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _json_object(value: str | None) -> dict[str, Any]:
    try:
        decoded = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


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
        result = {"threads": len(threads), "messages": len(messages), "threads_inserted": 0, "threads_updated": 0, "messages_inserted": 0, "messages_updated": 0}
        with self._conn() as conn:
            for t in threads.values():
                thread_id = t["id"]
                proposed = (
                    t.get("title"),
                    str(t.get("created_time") or ""),
                    str(t.get("last_edited_time") or t.get("updated_at") or ""),
                    None if t.get("alive") is None else int(bool(t.get("alive"))),
                    json.dumps(t.get("message_ids") or []),
                    json.dumps(t.get("raw") or {}),
                )
                existing = conn.execute(
                    "SELECT title,created_time,last_edited_time,alive,message_ids_json,raw_json FROM chat_threads WHERE id=?",
                    (thread_id,),
                ).fetchone()
                conn.execute(
                    """INSERT INTO chat_threads(id,title,created_time,last_edited_time,alive,message_ids_json,raw_json)
                    VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET title=excluded.title,last_edited_time=excluded.last_edited_time,alive=excluded.alive,message_ids_json=excluded.message_ids_json,raw_json=excluded.raw_json""",
                    (thread_id, *proposed),
                )
                if existing is None:
                    result["threads_inserted"] += 1
                elif tuple(existing) != proposed:
                    result["threads_updated"] += 1
            for m in messages.values():
                message_id = m["id"]
                proposed = (
                    m.get("thread_id"),
                    m.get("role"),
                    m.get("text") or "",
                    str(m.get("created_time") or ""),
                    json.dumps(m.get("raw") or {}),
                )
                existing = conn.execute(
                    "SELECT thread_id,role,text,created_time,raw_json FROM chat_messages WHERE id=?",
                    (message_id,),
                ).fetchone()
                conn.execute(
                    """INSERT INTO chat_messages(id,thread_id,role,text,created_time,raw_json)
                    VALUES(?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET thread_id=excluded.thread_id,role=excluded.role,text=excluded.text,created_time=excluded.created_time,raw_json=excluded.raw_json""",
                    (message_id, *proposed),
                )
                conn.execute("DELETE FROM chat_messages_fts WHERE id=?", (message_id,))
                conn.execute("INSERT INTO chat_messages_fts(id,thread_id,role,text) VALUES(?,?,?,?)", (message_id, m.get("thread_id"), m.get("role"), m.get("text") or ""))
                if existing is None:
                    result["messages_inserted"] += 1
                elif tuple(existing) != proposed:
                    result["messages_updated"] += 1
            conn.commit()
        return result

    def list_threads(self, limit: int = 50, offset: int = 0, include_inactive: bool = False) -> list[dict[str, Any]]:
        where = "" if include_inactive else "WHERE COALESCE(t.alive,1) != 0"
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT
                  t.id,
                  t.title,
                  t.created_time,
                  t.last_edited_time,
                  t.last_edited_time AS updated_at,
                  t.alive,
                  COUNT(m.id) AS message_count,
                  MIN(m.created_time) AS first_message_time,
                  MAX(m.created_time) AS last_message_time,
                  (
                    SELECT m1.text FROM chat_messages m1
                    WHERE m1.thread_id=t.id
                    ORDER BY m1.created_time, m1.id LIMIT 1
                  ) AS first_message_text,
                  (
                    SELECT m2.text FROM chat_messages m2
                    WHERE m2.thread_id=t.id
                    ORDER BY m2.created_time DESC, m2.id DESC LIMIT 1
                  ) AS last_message_text
                FROM chat_threads t
                LEFT JOIN chat_messages m ON m.thread_id=t.id
                {where}
                GROUP BY t.id
                ORDER BY COALESCE(NULLIF(t.last_edited_time,''), NULLIF(t.created_time,''), t.imported_at) DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["message_count"] = int(item.get("message_count") or 0)
                item["hydrated"] = item["message_count"] > 0
                item["first_message_preview"] = _preview(item.pop("first_message_text", ""))
                item["last_message_preview"] = _preview(item.pop("last_message_text", ""))
                out.append(item)
            return out

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            t = conn.execute("SELECT * FROM chat_threads WHERE id=?", (thread_id,)).fetchone()
            if not t:
                return None
            msgs = conn.execute("SELECT id,thread_id,role,text,created_time,raw_json FROM chat_messages WHERE thread_id=? ORDER BY created_time,id", (thread_id,)).fetchall()
        out = dict(t)
        out["message_ids"] = json.loads(out.pop("message_ids_json") or "[]")
        out["raw"] = _json_object(out.pop("raw_json") or "{}")
        messages: list[dict[str, Any]] = []
        for row in msgs:
            message = dict(row)
            message["raw"] = _json_object(message.pop("raw_json") or "{}")
            messages.append(message)
        out["messages"] = messages
        out["message_count"] = len(out["messages"])
        out["hydrated"] = out["message_count"] > 0
        out["first_message_preview"] = _preview(out["messages"][0].get("text") if out["messages"] else "")
        out["last_message_preview"] = _preview(out["messages"][-1].get("text") if out["messages"] else "")
        out["updated_at"] = out.get("last_edited_time") or out.get("created_time") or ""
        return out

    def debug_thread(self, thread_id: str) -> dict[str, Any]:
        thread = self.get_thread(thread_id)
        if not thread:
            return {"thread_exists": False, "message_count": 0, "raw_fields_seen": [], "known_message_fields_found": [], "sample": {}}
        return describe_thread_record(thread, thread.get("messages") or [])

    def search(self, query: str, limit: int = 25) -> list[dict[str, Any]]:
        query = str(query or "").strip()
        if not query:
            return []
        sql = "SELECT id,thread_id,role,snippet(chat_messages_fts,3,'[',']',' ... ',16) AS snippet FROM chat_messages_fts WHERE chat_messages_fts MATCH ? LIMIT ?"
        with self._conn() as conn:
            try:
                rows = conn.execute(sql, (query, limit)).fetchall()
            except sqlite3.OperationalError:
                try:
                    rows = conn.execute(sql, (_quote_fts_phrase(query), limit)).fetchall()
                except sqlite3.OperationalError as exc:
                    raise ValueError("Invalid chat-history search query") from exc
            return [dict(r) for r in rows]

    def thread_to_markdown(self, thread_id: str) -> str | None:
        thread = self.get_thread(thread_id)
        if not thread:
            return None
        lines = [f"# {thread.get('title') or thread.get('id')}", "", f"Thread ID: `{thread.get('id')}`", "", f"Messages: {thread.get('message_count', 0)}", ""]
        if not thread.get("messages"):
            lines += ["> This thread exists in the archive, but no message records are hydrated yet.", ""]
        for msg in thread.get("messages", []):
            lines += [f"## {str(msg.get('role') or 'message').title()}", "", str(msg.get("text") or ""), ""]
        return "\n".join(lines)
