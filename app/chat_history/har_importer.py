from __future__ import annotations

import base64
import json
from collections import Counter
from typing import Any
from urllib.parse import urlparse


def _json_loads(text: str | None, encoding: str | None = None) -> Any:
    if not text:
        return None
    if encoding == "base64":
        try:
            text = base64.b64decode(text).decode("utf-8", errors="replace")
        except Exception:
            return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _endpoint(entry: dict[str, Any]) -> str:
    try:
        path = urlparse(entry["request"]["url"]).path
    except Exception:
        return ""
    if not path.startswith("/api/v3/"):
        return ""
    return path.removeprefix("/api/v3")


def _request_json(entry: dict[str, Any]) -> Any:
    post_data = entry.get("request", {}).get("postData", {})
    return _json_loads(post_data.get("text"), post_data.get("encoding"))


def _response_json(entry: dict[str, Any]) -> Any:
    content = entry.get("response", {}).get("content", {})
    return _json_loads(content.get("text"), content.get("encoding"))


def _record_maps(obj: Any):
    if not isinstance(obj, dict):
        return
    record_map = obj.get("recordMap")
    if isinstance(record_map, dict):
        yield record_map
    for key in ("body", "data", "result"):
        nested = obj.get(key)
        if isinstance(nested, dict):
            yield from _record_maps(nested)


def _record_value(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    value = record.get("value")
    return value if isinstance(value, dict) else record


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
                out.append(item[0].strip())
            else:
                _collect_text(item, out, depth + 1)
        return
    if isinstance(value, dict):
        for key in ("text", "plain_text", "content", "message", "prompt", "response", "markdown", "title"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                out.append(candidate.strip())
        props = value.get("properties")
        if isinstance(props, dict):
            for prop in props.values():
                _collect_text(prop, out, depth + 1)
        for key in ("parts", "children", "value", "values", "blocks"):
            candidate = value.get(key)
            if isinstance(candidate, (list, dict)):
                _collect_text(candidate, out, depth + 1)


def _text_from_record(value: dict[str, Any]) -> str:
    chunks: list[str] = []
    _collect_text(value, chunks)
    unique: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        key = " ".join(chunk.split())
        if key and key not in seen:
            seen.add(key)
            unique.append(chunk)
    return "\n".join(unique)


def _message_ids(value: dict[str, Any]) -> list[str]:
    for key in ("messages", "message_ids", "thread_message_ids"):
        candidate = value.get(key)
        if isinstance(candidate, list):
            ids: list[str] = []
            for item in candidate:
                if isinstance(item, str):
                    ids.append(item)
                elif isinstance(item, dict) and isinstance(item.get("id"), str):
                    ids.append(item["id"])
            return ids
    return []


def _merge_records(bundle: dict[str, Any], obj: Any) -> None:
    for record_map in _record_maps(obj):
        for thread_id, record in (record_map.get("thread") or {}).items():
            value = _record_value(record)
            if not value:
                continue
            bundle["threads"][str(thread_id)] = {
                "id": str(thread_id),
                "title": value.get("title") or value.get("name"),
                "created_time": value.get("created_time"),
                "last_edited_time": value.get("last_edited_time"),
                "alive": value.get("alive") if isinstance(value.get("alive"), bool) else None,
                "message_ids": _message_ids(value),
                "raw": value,
            }
        for message_id, record in (record_map.get("thread_message") or {}).items():
            value = _record_value(record)
            if not value:
                continue
            bundle["messages"][str(message_id)] = {
                "id": str(message_id),
                "thread_id": value.get("thread_id") or value.get("parent_id") or value.get("threadId") or value.get("parentId"),
                "role": value.get("role") or value.get("type") or value.get("author_type"),
                "text": _text_from_record(value),
                "created_time": value.get("created_time"),
                "raw": value,
            }


def import_chat_object(obj: Any) -> dict[str, Any]:
    bundle = {"threads": {}, "messages": {}, "endpoint_counts": {}}
    _merge_records(bundle, obj)
    return bundle


def import_har_object(har: dict[str, Any]) -> dict[str, Any]:
    bundle = {"threads": {}, "messages": {}, "endpoint_counts": {}}
    counts: Counter[str] = Counter()
    entries = har.get("log", {}).get("entries", [])
    if not isinstance(entries, list):
        return bundle
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        endpoint = _endpoint(entry)
        if not endpoint:
            continue
        counts[endpoint] += 1
        _merge_records(bundle, _request_json(entry))
        _merge_records(bundle, _response_json(entry))
    bundle["endpoint_counts"] = dict(counts)
    return bundle
