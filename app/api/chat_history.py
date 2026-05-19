from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.chat_history.har_importer import import_chat_object, import_har_object
from app.chat_history.notion_sync import sync_chat_history_from_notion
from app.chat_history.store import ChatHistoryStore, get_default_chat_history_db_path
from app.notion_client import NotionUpstreamError

router = APIRouter(prefix="/chat-history", tags=["chat-history"])


def _store() -> ChatHistoryStore:
    return ChatHistoryStore()


@router.get("/status")
def status() -> dict[str, Any]:
    return {
        "status": "ok",
        "db_path": get_default_chat_history_db_path(),
        "capabilities": [
            "har_import",
            "notion_direct_sync",
            "hydration_diagnostics",
            "thread_debug",
            "local_archive",
            "local_search",
            "markdown_export",
        ],
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


@router.post("/sync/notion")
@router.post("/import/notion")
async def sync_from_notion(request: Request) -> dict[str, Any]:
    """Pull chat history directly from the configured Notion account into the local archive."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}

    account_index = payload.get("account_index", 0)
    limit = payload.get("limit", 100)
    max_pages = payload.get("max_pages", 5)

    try:
        account_index = int(account_index)
        limit = max(1, min(int(limit), 500))
        max_pages = max(1, min(int(max_pages), 20))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid import parameters") from exc

    pool = request.app.state.account_pool
    clients = getattr(pool, "clients", [])
    if not clients:
        raise HTTPException(status_code=503, detail="No configured Notion accounts are available")
    if account_index < 0 or account_index >= len(clients):
        raise HTTPException(status_code=400, detail="account_index is out of range")

    client = clients[account_index]
    try:
        bundle = sync_chat_history_from_notion(client, limit=limit, max_pages=max_pages)
    except NotionUpstreamError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": {
                    "message": "Unable to fetch chat history from Notion.",
                    "type": "upstream_error",
                    "param": None,
                    "code": "upstream_error",
                    "detail": exc.response_excerpt,
                }
            },
        ) from exc

    imported = _store().upsert_bundle(bundle)
    summary = dict(bundle.get("sync_summary", {}))
    summary.update(
        {
            "threads_inserted": imported.get("threads_inserted", 0),
            "threads_updated": imported.get("threads_updated", 0),
            "messages_inserted": imported.get("messages_inserted", 0),
            "messages_updated": imported.get("messages_updated", 0),
        }
    )
    return {
        "imported": imported,
        "endpoint_counts": bundle.get("endpoint_counts", {}),
        "source": "notion_direct_sync",
        "account_index": account_index,
        "stats": bundle.get("stats", {}),
        "sync_summary": summary,
    }


@router.get("/threads")
def list_threads(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict[str, Any]:
    return {"threads": _store().list_threads(limit=limit, offset=offset)}


@router.get("/threads/{thread_id}")
def get_thread(thread_id: str) -> dict[str, Any]:
    thread = _store().get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


@router.get("/threads/{thread_id}/debug")
def debug_thread(thread_id: str) -> dict[str, Any]:
    return _store().debug_thread(thread_id)


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
