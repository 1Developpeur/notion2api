from __future__ import annotations

from typing import Any

THREAD_MESSAGE_FIELDS = (
    "messages",
    "message_ids",
    "thread_message_ids",
    "messageIds",
    "threadMessageIds",
    "conversation_messages",
    "conversationMessages",
    "records",
    "items",
)

MESSAGE_ID_FIELDS = ("id", "message_id", "messageId", "uuid")
MESSAGE_ROLE_FIELDS = ("role", "author_role", "authorRole", "type")
MESSAGE_TEXT_FIELDS = ("content", "text", "markdown", "message", "body")
THREAD_ID_FIELDS = ("thread_id", "threadId", "parent_id", "parentId", "conversation_id", "conversationId")
THREAD_UPDATED_FIELDS = ("updated_at", "updatedAt", "last_edited_time", "lastEditedTime", "last_updated_time", "lastUpdatedTime")
THREAD_CREATED_FIELDS = ("created_time", "createdTime", "created_at", "createdAt")
SECRET_KEY_FRAGMENTS = ("token", "cookie", "authorization", "api_key", "apikey", "secret", "password", "session")


def record_value(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    value = record.get("value")
    return value if isinstance(value, dict) else record


def record_maps(obj: Any):
    if not isinstance(obj, dict):
        return
    record_map = obj.get("recordMap")
    if isinstance(record_map, dict):
        yield record_map
    for key in ("body", "data", "result"):
        nested = obj.get(key)
        if isinstance(nested, dict):
            yield from record_maps(nested)


def _first_str(value: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _coerce_text(value: Any) -> str:
    chunks: list[str] = []
    _collect_text(value, chunks)
    unique: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        key = " ".join(str(chunk).split())
        if key and key not in seen:
            seen.add(key)
            unique.append(str(chunk).strip())
    return "\n".join(unique)


def _collect_text(value: Any, out: list[str], depth: int = 0) -> None:
    if depth > 8:
        return
    if isinstance(value, str):
        if value.strip():
            out.append(value.strip())
        return
    if isinstance(value, list):
        for item in value:
            if isinstance(item, list) and item and isinstance(item[0], str):
                if item[0].strip():
                    out.append(item[0].strip())
            else:
                _collect_text(item, out, depth + 1)
        return
    if isinstance(value, dict):
        for key in ("text", "plain_text", "content", "message", "prompt", "response", "markdown", "title", "body"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                out.append(candidate.strip())
        props = value.get("properties")
        if isinstance(props, dict):
            for prop in props.values():
                _collect_text(prop, out, depth + 1)
        for key in ("parts", "children", "value", "values", "blocks", "rich_text"):
            candidate = value.get(key)
            if isinstance(candidate, (list, dict)):
                _collect_text(candidate, out, depth + 1)


def _extract_id(candidate: Any) -> str | None:
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    if isinstance(candidate, dict):
        for key in MESSAGE_ID_FIELDS:
            value = candidate.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        pointer = candidate.get("pointer")
        if isinstance(pointer, dict):
            value = pointer.get("id")
            if isinstance(value, str) and value.strip():
                return value.strip()
        value = candidate.get("value")
        if isinstance(value, dict):
            return _extract_id(value)
    return None


def _extract_ids(candidate: Any, depth: int = 0) -> list[str]:
    if depth > 5:
        return []
    direct = _extract_id(candidate)
    if direct:
        return [direct]
    ids: list[str] = []
    if isinstance(candidate, list):
        for item in candidate:
            ids.extend(_extract_ids(item, depth + 1))
    elif isinstance(candidate, dict):
        thread_message_map = candidate.get("thread_message")
        if isinstance(thread_message_map, dict):
            ids.extend(str(key) for key in thread_message_map.keys() if str(key).strip())
            for record in thread_message_map.values():
                ids.extend(_extract_ids(record, depth + 1))
        record_map = candidate.get("recordMap")
        if isinstance(record_map, dict):
            ids.extend(_extract_ids(record_map, depth + 1))
        for key in ("records", "items", "messages", "value", "values"):
            nested = candidate.get(key)
            if isinstance(nested, (list, dict)):
                ids.extend(_extract_ids(nested, depth + 1))
    return _dedupe(ids)


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = str(value or "").strip()
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def extract_message_ids(value: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in THREAD_MESSAGE_FIELDS:
        if key in value:
            ids.extend(_extract_ids(value.get(key)))
    return _dedupe(ids)


def normalize_thread(thread_id: str | None, raw: dict[str, Any]) -> dict[str, Any] | None:
    value = record_value(raw)
    resolved_id = thread_id or _first_str(value, ("id", "thread_id", "threadId", "uuid"))
    if not resolved_id:
        return None
    updated_at = _first_str(value, THREAD_UPDATED_FIELDS)
    created_at = _first_str(value, THREAD_CREATED_FIELDS)
    return {
        "id": str(resolved_id),
        "title": value.get("title") or value.get("name"),
        "created_time": created_at or value.get("created_time") or value.get("createdTime"),
        "last_edited_time": updated_at or value.get("last_edited_time") or value.get("lastEditedTime"),
        "updated_at": updated_at,
        "alive": value.get("alive") if isinstance(value.get("alive"), bool) else None,
        "message_ids": extract_message_ids(value),
        "raw": value,
    }


def normalize_message(message_id: str | None, raw: dict[str, Any], fallback_thread_id: str | None = None) -> dict[str, Any] | None:
    value = record_value(raw)
    resolved_id = message_id or _first_str(value, MESSAGE_ID_FIELDS)
    text = _coerce_text({key: value.get(key) for key in MESSAGE_TEXT_FIELDS if key in value}) or _coerce_text(value)
    if not resolved_id and not text:
        return None
    thread_id = _first_str(value, THREAD_ID_FIELDS) or fallback_thread_id
    role = _first_str(value, MESSAGE_ROLE_FIELDS)
    created_at = _first_str(value, THREAD_CREATED_FIELDS)
    return {
        "id": str(resolved_id or f"synthetic-{abs(hash((thread_id, text))) }"),
        "thread_id": thread_id,
        "role": role,
        "text": text,
        "created_time": created_at or value.get("created_time") or value.get("createdTime"),
        "raw": value,
    }


def _iter_collection(obj: Any, names: tuple[str, ...]):
    if not isinstance(obj, dict):
        return
    for name in names:
        collection = obj.get(name)
        if isinstance(collection, list):
            for item in collection:
                if isinstance(item, dict):
                    yield None, item
        elif isinstance(collection, dict):
            for key, item in collection.items():
                if isinstance(item, dict):
                    yield str(key), item
    for key in ("body", "data", "result"):
        nested = obj.get(key)
        if isinstance(nested, dict):
            yield from _iter_collection(nested, names)


def _merge_thread_candidate(bundle: dict[str, Any], fallback_id: str | None, candidate: dict[str, Any]) -> None:
    thread = normalize_thread(fallback_id, candidate)
    if not thread:
        return
    thread_id = thread["id"]
    direct_message_ids = list(thread.get("message_ids") or [])
    value = record_value(candidate)
    for field in THREAD_MESSAGE_FIELDS:
        items = value.get(field)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            message = normalize_message(None, item, fallback_thread_id=thread_id)
            if message:
                bundle["messages"][message["id"]] = message
                direct_message_ids.append(message["id"])
    thread["message_ids"] = _dedupe(direct_message_ids)
    bundle["threads"][thread_id] = thread


def merge_records_into_bundle(bundle: dict[str, Any], obj: Any) -> None:
    for record_map in record_maps(obj):
        for thread_id, record in (record_map.get("thread") or {}).items():
            thread = normalize_thread(str(thread_id), record_value(record))
            if thread:
                bundle["threads"][thread["id"]] = thread
        for message_id, record in (record_map.get("thread_message") or {}).items():
            message = normalize_message(str(message_id), record_value(record))
            if message:
                bundle["messages"][message["id"]] = message

    if isinstance(obj, dict):
        for fallback_id, candidate in _iter_collection(obj, ("transcripts", "threads")):
            _merge_thread_candidate(bundle, fallback_id, candidate)
        for fallback_id, candidate in _iter_collection(obj, ("messages", "thread_messages", "threadMessages")):
            message = normalize_message(fallback_id, candidate)
            if message:
                bundle["messages"][message["id"]] = message


def redact_secrets(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "[redacted-depth-limit]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in SECRET_KEY_FRAGMENTS):
                out[str(key)] = "[redacted]"
            else:
                out[str(key)] = redact_secrets(item, depth + 1)
        return out
    if isinstance(value, list):
        return [redact_secrets(item, depth + 1) for item in value[:20]]
    return value
