from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from app.logger import logger

_PATCHED = False


def _conversation_id_from_request(req_body: Any) -> str:
    return str(getattr(req_body, "conversation_id", None) or "").strip()


def _manager_from_request(request: Any) -> Any | None:
    return getattr(getattr(request, "app", None).state, "conversation_manager", None)


def _conversation_exists(manager: Any, conversation_id: str) -> bool:
    try:
        return bool(manager and conversation_id and manager.conversation_exists(conversation_id))
    except Exception:
        return False


def _get_bound_thread_id(manager: Any, conversation_id: str) -> str | None:
    if not _conversation_exists(manager, conversation_id):
        return None
    try:
        thread_id = manager.get_conversation_thread_id(conversation_id)
    except Exception:
        return None
    clean = str(thread_id or "").strip()
    return clean or None


def _set_bound_thread_id(manager: Any, conversation_id: str, thread_id: str | None) -> None:
    clean = str(thread_id or "").strip()
    if not clean or not _conversation_exists(manager, conversation_id):
        return
    try:
        manager.set_conversation_thread_id(conversation_id, clean)
    except Exception:
        logger.warning(
            "Unable to persist resumed chat thread binding",
            exc_info=True,
            extra={
                "request_info": {
                    "event": "resume_thread_binding_persist_failed",
                    "conversation_id": conversation_id,
                    "thread_id": clean,
                }
            },
        )


def _patch_pool_for_request(request: Any, conversation_id: str) -> Callable[[], None]:
    """Temporarily patch pool.get_client so standard/lite modes honor conversation thread IDs.

    The existing standard/lite handlers intentionally do not touch ConversationManager.
    Rather than duplicating their full implementations, this wrapper intercepts the selected
    Notion client and rewrites stream_response(thread_id=None) to the stored thread id when
    one exists. If no thread id exists yet, it persists the one created by stream_response.
    """
    manager = _manager_from_request(request)
    if not manager or not _conversation_exists(manager, conversation_id):
        return lambda: None

    pool = getattr(getattr(request, "app", None).state, "account_pool", None)
    if not pool or not hasattr(pool, "get_client"):
        return lambda: None

    original_get_client = pool.get_client
    touched: list[tuple[Any, Any]] = []

    def patched_get_client(*args: Any, **kwargs: Any) -> Any:
        client = original_get_client(*args, **kwargs)
        original_stream_response = getattr(client, "stream_response", None)
        if not callable(original_stream_response):
            return client

        bound_thread_id = _get_bound_thread_id(manager, conversation_id)

        @wraps(original_stream_response)
        def patched_stream_response(transcript: Any, thread_id: str | None = None, attachments: list[Any] | None = None):
            active_thread_id = thread_id or bound_thread_id
            stream = original_stream_response(
                transcript,
                thread_id=active_thread_id,
                attachments=attachments,
            )
            if not bound_thread_id:
                created_thread_id = getattr(client, "current_thread_id", None)
                _set_bound_thread_id(manager, conversation_id, created_thread_id)
            return stream

        client.stream_response = patched_stream_response
        touched.append((client, original_stream_response))
        return client

    pool.get_client = patched_get_client

    def restore() -> None:
        pool.get_client = original_get_client
        for client, original_stream_response in touched:
            try:
                client.stream_response = original_stream_response
            except Exception:
                pass

    return restore


def _wrap_handler(handler: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(handler)
    async def wrapped(request: Any, req_body: Any, *args: Any, **kwargs: Any) -> Any:
        conversation_id = _conversation_id_from_request(req_body)
        if not conversation_id:
            return await handler(request, req_body, *args, **kwargs)
        restore = _patch_pool_for_request(request, conversation_id)
        try:
            return await handler(request, req_body, *args, **kwargs)
        finally:
            restore()

    return wrapped


def apply_chat_resume_thread_bindings() -> None:
    global _PATCHED
    if _PATCHED:
        return

    from app.api import chat as chat_module

    chat_module._handle_standard_request = _wrap_handler(chat_module._handle_standard_request)
    chat_module._handle_lite_request = _wrap_handler(chat_module._handle_lite_request)
    _PATCHED = True

    logger.info(
        "Chat resume thread bindings patched into standard/lite handlers",
        extra={"request_info": {"event": "resume_thread_binding_patch_applied"}},
    )
