from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.chat_history.har_importer import import_har_object
from app.chat_history.store import ChatHistoryStore, get_default_chat_history_db_path

router = APIRouter(prefix="/chat-history", tags=["chat-history"])


def _store() -> ChatHistoryStore:
    return ChatHistoryStore()


@router.get("/status")
def status() -> dict[str, Any]:
    return {
        "status": "ok",
        "db_path": get_default_chat_history_db_path(),
        "capabilities": ["har_import", "local_archive", "local_search", "markdown_export"],
    }


@router.post("/import/har")
async def import_har(request: Request) -> dict[str, Any]:
    """Import a browser HAR JSON object containing Notion AI chat-history records."""
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Request body must be JSON") from exc

    har = payload.get("har") if isinstance(payload, dict) and "har" in payload else payload
    if not isinstance(har, dict):
        raise HTTPException(status_code=400, detail="HAR payload must be a JSON object")

    bundle = import_har_object(har)
    imported = _store().upsert_bundle(bundle)
    return {"imported": imported, "endpoint_counts": bundle.get("endpoint_counts", {})}


@router.get("/threads")
def list_threads(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict[str, Any]:
    return {"threads": _store().list_threads(limit=limit, offset=offset)}


@router.get("/threads/{thread_id}")
def get_thread(thread_id: str) -> dict[str, Any]:
    thread = _store().get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


@router.get("/threads/{thread_id}/markdown", response_class=PlainTextResponse)
def export_markdown(thread_id: str) -> str:
    markdown = _store().thread_to_markdown(thread_id)
    if markdown is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return markdown


@router.get("/search")
def search(q: str = Query(..., min_length=1), limit: int = Query(25, ge=1, le=100)) -> dict[str, Any]:
    try:
        return {"results": _store().search(q, limit=limit)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
