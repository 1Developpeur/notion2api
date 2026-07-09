from __future__ import annotations

from typing import Any

TITLE_MAX_LEN = 240


def resolve_requested_thread_title(
    *,
    chat_title: str | None = None,
    title: str | None = None,
    session_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Resolve the canonical requested thread title from transport fields."""
    meta = metadata if isinstance(metadata, dict) else {}
    for candidate in (
        chat_title,
        title,
        session_name,
        meta.get("repo_ai_thread_title"),
        meta.get("chat_title"),
        meta.get("title"),
        meta.get("session_name"),
    ):
        text = str(candidate or "").strip()
        if text:
            return text[:TITLE_MAX_LEN]
    return ""
