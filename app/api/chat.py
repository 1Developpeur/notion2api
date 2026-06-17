# pylint: disable=broad-exception-caught, protected-access
import asyncio
import json
import re
import time
import uuid
from difflib import SequenceMatcher
from typing import Any, Dict, Generator, Iterable, List, Tuple

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.errors import openai_error
from app.core.models import normalize_model_id
from app.conversation import compress_round_if_needed, compress_sliding_window_round, build_lite_transcript
from app.config import is_lite_mode
from app.logger import logger
from app.model_registry import is_supported_model, list_available_models
from app.notion_client import NotionUpstreamError
from app.attachments.normalizer import normalize_chat_messages
from app.attachments.security import AttachmentPolicy
from app.attachments.errors import AttachmentError
from app.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    ChatMessageResponseChoice,
)

router = APIRouter()


# Structured error responses
def _classify_upstream_error(exc: NotionUpstreamError) -> dict[str, Any]:
    """Classify NotionUpstreamError into frontend-safe structured error details."""
    sc = exc.status_code

    if sc == 401:
        return {
            "code": "NOTION_401",
            "type": "upstream_auth_error",
            "message": "Notion authentication failed (HTTP 401). The saved session may be expired.",
            "suggestion": "Refresh the local login session and update configuration.",
        }
    if sc == 403:
        return {
            "code": "NOTION_403",
            "type": "upstream_forbidden",
            "message": "Notion denied access (HTTP 403). Cloudflare or account restrictions may be involved.",
            "suggestion": "Check server network access or retry later.",
        }
    if sc == 429:
        return {
            "code": "NOTION_429",
            "type": "upstream_rate_limit",
            "message": "Notion request rate is too high (HTTP 429).",
            "suggestion": "Wait briefly before retrying, or configure multiple accounts to spread requests.",
        }
    if sc and sc >= 500:
        return {
            "code": f"NOTION_{sc}",
            "type": "upstream_server_error",
            "message": f"Notion is temporarily unavailable (HTTP {sc}).",
            "suggestion": "The Notion upstream service failed. Retry later.",
        }
    if "timed out" in str(exc).lower():
        return {
            "code": "NETWORK_TIMEOUT",
            "type": "network_timeout",
            "message": "Connection to Notion timed out.",
            "suggestion": "Check network connectivity from the server to notion.so.",
        }
    if "failed" in str(exc).lower() and not sc:
        return {
            "code": "NETWORK_ERROR",
            "type": "network_error",
            "message": "Unable to connect to the Notion service.",
            "suggestion": "Check server network and DNS configuration.",
        }
    if "empty" in str(exc).lower():
        return {
            "code": "NOTION_EMPTY",
            "type": "upstream_empty_response",
            "message": "Notion returned empty content.",
            "suggestion": "Send the message again.",
        }
    return {
        "code": "UPSTREAM_UNKNOWN",
        "type": "upstream_error",
        "message": str(exc),
        "suggestion": "Retry later.",
    }


def _build_error_response(
    status_code: int,
    *,
    code: str,
    message: str,
    error_type: str = "server_error",
    param: str | None = None,
    suggestion: str = "",
    detail: str = "",
) -> JSONResponse:
    """Build a unified JSON error response that the frontend can parse."""
    content: dict[str, Any] = {
        "error": {
            "message": message,
            "type": error_type,
            "param": param,
            "code": code,
        }
    }
    if suggestion:
        content["error"]["suggestion"] = suggestion
    if detail:
        content["error"]["detail"] = detail
    return JSONResponse(status_code=status_code, content=content)


def _upstream_error_response(exc: NotionUpstreamError) -> JSONResponse:
    """Convert NotionUpstreamError to a unified 503 JSON response."""
    info = _classify_upstream_error(exc)
    return _build_error_response(
        503,
        code=info["code"],
        message=info["message"],
        error_type=info["type"],
        suggestion=info.get("suggestion", ""),
        detail=exc.response_excerpt or "",
    )


def _resolve_request_model(model: str | None) -> str:
    normalized_model = normalize_model_id(model)
    if not normalized_model:
        openai_error("The 'model' field is required.", "model_required")
    if not is_supported_model(normalized_model):
        available_models = list_available_models()
        openai_error(
            f"Unsupported model '{normalized_model}'. Available models: {', '.join(available_models)}",
            "model_not_found",
        )
    return normalized_model


def _local_probe_response_text(content: Any) -> str:
    """Return a local response for health/preflight prompts that must not persist."""
    if not isinstance(content, str):
        return ""

    normalized = " ".join(content.strip().split()).lower()
    if normalized in {
        "reply with ok.",
        "reply with ok",
        "respond with ok.",
        "respond with ok",
    }:
        return "OK"
    if normalized in {
        "ping! respond with exactly 'pong' to verify connection.",
        "reply with exactly: pong",
        "reply with exactly pong",
    }:
        return "pong"
    return ""


RECALL_INTENT_KEYWORDS = [
    "history",
    "history",
    "history",
    "history",
    "history",
    "earlier",
    "before",
    "recall",
    "remember",
    "history",
    "history",
    "history",
    "history",
]


def _build_stream_chunk(
    response_id: str,
    model: str,
    *,
    content: str = "",
    thinking: str = "",
    role: str = "",
    finish_reason=None,
) -> str:
    delta: Dict[str, Any] = {}
    if role:
        delta["role"] = role
    if content:
        delta["content"] = content
    if thinking:
        delta["reasoning_content"] = thinking

    payload = {
        "id": response_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _build_local_ui_chunk(
    response_id: str,
    model: str,
    event_type: str,
    **payload_fields: Any,
) -> str:
    payload: Dict[str, Any] = {
        "id": response_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
        "type": event_type,
    }
    payload.update(payload_fields)
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _format_search_results_md(search_data: dict[str, Any]) -> str:
    """Format search data as Markdown for standard clients."""
    lines = []
    queries = search_data.get("queries", [])
    if queries:
        lines.append(f"> 🔍 **Searched:** {', '.join(queries)}")

    sources = search_data.get("sources", [])
    if sources:
        lines.append("> 🌐 **Searched:**")
        for i, src in enumerate(sources[:5], 1):  # text5text
            title = src.get("title") or src.get("url") or "Unknown source"
            url = src.get("url")
            if url:
                lines.append(f"> {i}. [{title}]({url})")
            else:
                lines.append(f"> {i}. {title}")

    if lines:
        return "\n".join(lines) + "\n\n"
    return ""


def _normalize_stream_item(item: Any) -> dict[str, Any]:
    if isinstance(item, str):
        return {"type": "content", "text": item}

    if isinstance(item, dict):
        item_type = str(item.get("type", "") or "").lower()
        if item_type == "content":
            return {"type": "content", "text": str(item.get("text") or item.get("history", "") or "")}
        if item_type == "search":
            payload = item.get("data")
            return {
                "type": "search",
                "data": payload if isinstance(payload, dict) else {},
            }
        if item_type == "thinking":
            return {"type": "thinking", "text": str(item.get("text") or item.get("history", "") or "")}
        if item_type == "final_content":
            return {
                "type": "final_content",
                "text": str(item.get("text") or item.get("history", "") or ""),
                "source_type": str(item.get("source_type", "") or ""),
                "source_length": item.get("source_length"),
                "model_metadata": item.get("model_metadata") if isinstance(item.get("model_metadata"), dict) else {},
            }
        if item_type == "model_metadata":
            payload = item.get("data")
            return {
                "type": "model_metadata",
                "data": payload if isinstance(payload, dict) else {},
            }

    return {"type": "unknown"}


def _iter_stream_items(
    first_item: Any, stream_gen: Iterable[Any]
) -> Generator[Any, None, None]:
    if first_item is not None:
        yield first_item
    for item in stream_gen:
        yield item


def _merge_model_metadata(current: dict[str, Any] | None, item: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(current or {})
    payload: Any = None
    item_type = str(item.get("type", "") or "")
    if item_type == "model_metadata":
        payload = item.get("data")
    elif item_type == "final_content":
        payload = item.get("model_metadata")
    if not isinstance(payload, dict):
        return merged
    for key, value in payload.items():
        if value not in (None, "", [], {}):
            merged[str(key)] = value
    return merged


def _response_model_metadata(requested_model: str, model_metadata: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(model_metadata or {})
    requested = normalize_model_id(requested_model) or requested_model
    if requested:
        payload.setdefault("requested_model", requested)
        try:
            from app.model_registry import get_notion_model
            payload.setdefault("notion_requested_model", get_notion_model(requested))
        except Exception:
            pass
    actual = payload.get("actual_model") or payload.get("notion_model_name") or payload.get("notion_step_model")
    if actual:
        payload["actual_model"] = actual
    return {k: v for k, v in payload.items() if v not in (None, "", [], {})}


def _attach_response_model_metadata(response_obj: ChatCompletionResponse, requested_model: str, model_metadata: dict[str, Any] | None) -> None:
    payload = _response_model_metadata(requested_model, model_metadata)
    if not payload:
        return
    response_obj.requested_model = payload.get("requested_model")
    response_obj.notion_requested_model = payload.get("notion_requested_model")
    response_obj.actual_model = payload.get("actual_model")
    response_obj.model_metadata = payload

    # The OpenAI-compatible response `model` should identify the responder,
    # not merely the user's requested alias. Preserve the alias separately in
    # requested_model / notion_requested_model.
    actual_model = payload.get("actual_model")
    if isinstance(actual_model, str) and actual_model.strip():
        response_obj.model = actual_model.strip()


def _build_model_metadata_event(requested_model: str, model_metadata: dict[str, Any] | None) -> str:
    payload = _response_model_metadata(requested_model, model_metadata)
    if not payload:
        return ""
    actual_model = payload.get("actual_model")
    if isinstance(actual_model, str) and actual_model.strip():
        payload["display_model"] = actual_model.strip()
    event = {"type": "model_metadata", "model_metadata": payload}
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _compute_missing_suffix(current_text: str, final_text: str) -> str:
    if not final_text:
        return ""
    if not current_text:
        return final_text
    if final_text.startswith(current_text):
        return final_text[len(current_text) :]
    return ""


def _select_best_final_reply(
    streamed_text: str,
    final_text: str,
    final_source_type: str,
) -> tuple[str, str]:
    streamed = streamed_text or ""
    final = final_text or ""
    streamed_stripped = streamed.strip()
    final_stripped = final.strip()
    source = (final_source_type or "").strip().lower()

    if not final_stripped:
        return streamed, "streamed_only"
    if not streamed_stripped:
        return final, "final_only"
    if final.startswith(streamed):
        return final, "final_extends_streamed"
    if streamed.startswith(final):
        if source == "title" or len(final_stripped) <= max(
            32, int(len(streamed_stripped) * 0.35)
        ):
            return streamed, "streamed_beats_short_final"
        return final, "final_prefix_of_streamed"

    # Diverged content: usually prefer richer non-title final content.
    if source == "title" and len(final_stripped) < max(
        48, int(len(streamed_stripped) * 0.6)
    ):
        return streamed, "streamed_beats_title"
    if len(final_stripped) >= max(48, int(len(streamed_stripped) * 0.6)):
        return final, "final_diverged_preferred"
    return streamed, "streamed_diverged_preferred"


def _normalize_overlap_text(text: str) -> str:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return ""
    normalized = re.sub(r"```.*?```", " ", normalized, flags=re.DOTALL)
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def _trim_redundant_thinking(
    thinking_text: str, final_reply: str
) -> tuple[str, str, float]:
    thinking = str(thinking_text or "").strip()
    final = str(final_reply or "").strip()
    if not thinking or not final:
        return thinking, "missing_text", 0.0

    normalized_thinking = _normalize_overlap_text(thinking)
    normalized_final = _normalize_overlap_text(final)
    if not normalized_thinking or not normalized_final:
        return thinking, "missing_normalized_text", 0.0

    overlap_ratio = SequenceMatcher(None, normalized_thinking, normalized_final).ratio()
    if normalized_thinking == normalized_final:
        return "", "identical", overlap_ratio

    if thinking.endswith(final):
        prefix = thinking[: -len(final)].rstrip()
        if len(_normalize_overlap_text(prefix)) >= 10:
            return prefix, "suffix_trimmed", overlap_ratio
        return "", "suffix_cleared", overlap_ratio

    if overlap_ratio >= 0.92 and (
        normalized_thinking in normalized_final
        or normalized_final in normalized_thinking
    ):
        return "", "high_overlap_cleared", overlap_ratio

    return thinking, "kept", overlap_ratio


def _build_thinking_replacement(
    streamed_content_text: str,
    thinking_text: str,
    final_reply: str,
    final_source_type: str,
) -> dict[str, Any] | None:
    source = str(final_source_type or "").strip().lower()

    # Relax constraint: Allow replacement for more source types to fix Sonnet thinking leakage
    # But still require minimal validation for non-inference sources
    if source not in ("agent-inference", "history", "markdown-chat", ""):
        # Only skip for clearly non-thinking source types
        return None

    normalized_final = _normalize_overlap_text(final_reply)
    normalized_streamed = _normalize_overlap_text(streamed_content_text)

    # Require at least some thinking content to process
    if not _normalize_overlap_text(thinking_text):
        return None

    # For non-agent-inference sources, be more conservative but still check for obvious duplication
    if source != "agent-inference":
        # Only process if there's clear overlap or thinking is redundant
        if not normalized_final:
            return None

        # Check for obvious duplication (thinking appears in final reply)
        if thinking_text.strip() in final_reply or final_reply in thinking_text:
            # Clear case of duplication - trim it
            replacement, decision, overlap_ratio = _trim_redundant_thinking(
                thinking_text, final_reply
            )
            if replacement != str(thinking_text or "").strip():
                logger.debug(
                    "Non-agent-inference thinking replacement applied",
                    extra={
                        "request_info": {
                            "event": "thinking_replacement_non_agent",
                            "source_type": source,
                            "overlap_ratio": round(overlap_ratio, 4),
                            "decision": f"{decision}_non_agent_inference",
                        }
                    },
                )
                return {
                    "thinking": replacement,
                    "decision": f"{decision}_non_agent_inference",
                    "overlap_ratio": round(overlap_ratio, 4),
                    "source_type": source,
                }
        return None

    # Original agent-inference logic continues
    if not normalized_final:
        return None

    # text
    if normalized_streamed and len(normalized_streamed) >= max(
        10, int(len(normalized_final) * 0.35)
    ):
        return None

    replacement, decision, overlap_ratio = _trim_redundant_thinking(
        thinking_text, final_reply
    )
    if replacement == str(thinking_text or "").strip():
        return None

    return {
        "thinking": replacement,
        "decision": decision,
        "overlap_ratio": round(overlap_ratio, 4),
        "source_type": source,
    }


def _contains_recall_intent(text: str) -> bool:
    lowered = text.lower()
    for keyword in RECALL_INTENT_KEYWORDS:
        if keyword.isascii():
            if keyword.lower() in lowered:
                return True
            continue
        if keyword in text:
            return True
    return False


def _extract_recall_query(text: str) -> str:
    cleaned = text
    for keyword in RECALL_INTENT_KEYWORDS:
        if keyword.isascii():
            cleaned = re.sub(
                rf"\b{re.escape(keyword)}\b", " ", cleaned, flags=re.IGNORECASE
            )
        else:
            cleaned = cleaned.replace(keyword, " ")
    cleaned = re.sub(r"[\stext,.!?;:text]+", " ", cleaned).strip()
    return cleaned or text.strip()


def _prepare_messages(
    req_body: ChatCompletionRequest,
) -> Tuple[str, List[Tuple[str, str, str]], str]:
    system_messages = []
    dialogue_messages = []

    for msg in req_body.messages:
        if msg.role == "system":
            if msg.content.strip():
                system_messages.append(msg.content.strip())
            continue
        dialogue_messages.append((msg.role, msg.content, msg.thinking or ""))

    if not dialogue_messages:
        raise HTTPException(
            status_code=400,
            detail="The messages list must contain at least one user message.",
        )

    last_role, user_prompt, _ = dialogue_messages[-1]
    raw_user_prompt = user_prompt
    history_messages = dialogue_messages[:-1]

    if last_role != "user":
        raise HTTPException(
            status_code=400, detail="The last message must be from role 'user'."
        )
    if not user_prompt.strip():
        raise HTTPException(
            status_code=400, detail="The last user message cannot be empty."
        )

    if system_messages:
        merged_system_prompt = "\n".join(system_messages)
        user_prompt = f"[System Instructions: {merged_system_prompt}]\n\n{user_prompt}"

    return user_prompt, history_messages, raw_user_prompt


def _prepare_messages_lite(req_body: ChatCompletionRequest) -> str:
    """Lite text user text system text"""
    system_messages = []
    user_prompt = ""

    for msg in req_body.messages:
        if msg.role == "system" and msg.content.strip():
            system_messages.append(msg.content.strip())
        elif msg.role == "user":
            user_prompt = msg.content

    if not user_prompt.strip():
        raise HTTPException(
            status_code=400,
            detail="The messages list must contain at least one user message.",
        )

    if system_messages:
        user_prompt = (
            f"[System Instructions: {' '.join(system_messages)}]\n\n{user_prompt}"
        )

    return user_prompt


def _create_lite_stream_generator(
    response_id: str,
    model_name: str,
    first_item: Any,
    stream_gen: Iterable[Any],
) -> Generator[str, None, None]:
    """Lite text contenttext thinking text search"""
    streamed_content_accumulator = ""
    authoritative_final_content = ""
    authoritative_final_source_type = ""
    model_metadata: dict[str, Any] = {}
    assistant_started = False

    try:
        for raw_item in _iter_stream_items(first_item, stream_gen):
            item = _normalize_stream_item(raw_item)
            item_type = item.get("type")

            model_metadata = _merge_model_metadata(model_metadata, item)
            if item_type == "model_metadata":
                continue

            if item_type == "final_content":
                final_text = str(item.get("text", "") or "").strip()
                if final_text:
                    authoritative_final_content = final_text
                    authoritative_final_source_type = str(
                        item.get("source_type", "") or ""
                    )
                continue

            # Lite text thinking text search
            if item_type in ("thinking", "search"):
                continue

            if item_type != "content":
                continue

            chunk_text = item.get("text", "")
            if not chunk_text:
                continue

            streamed_content_accumulator += chunk_text
            if not assistant_started:
                assistant_started = True
                yield _build_stream_chunk(
                    response_id,
                    model_name,
                    role="assistant",
                    content=chunk_text,
                )
            else:
                yield _build_stream_chunk(response_id, model_name, content=chunk_text)
    except asyncio.CancelledError:
        logger.info(
            "Lite streaming cancelled by client",
            extra={"request_info": {"event": "lite_stream_cancelled"}},
        )
        raise
    except Exception as exc:
        if _is_client_disconnect_error(exc):
            logger.info(
                "Lite streaming connection closed by client",
                extra={"request_info": {"event": "lite_stream_client_disconnected"}},
            )
            return
        logger.error(
            "Lite streaming interrupted",
            exc_info=True,
            extra={"request_info": {"event": "lite_stream_interrupted"}},
        )
        error_hint = "\n\n[Upstream connection interrupted. Retry later.]"
        streamed_content_accumulator += error_hint
        if not assistant_started:
            assistant_started = True
            yield _build_stream_chunk(
                response_id,
                model_name,
                role="assistant",
                content=error_hint,
            )
        else:
            yield _build_stream_chunk(response_id, model_name, content=error_hint)
    finally:
        # text
        final_reply, _ = _select_best_final_reply(
            streamed_content_accumulator,
            authoritative_final_content,
            authoritative_final_source_type,
        )

        # text
        missing_suffix = _compute_missing_suffix(
            streamed_content_accumulator, final_reply
        )
        if missing_suffix:
            if not assistant_started:
                assistant_started = True
                yield _build_stream_chunk(
                    response_id,
                    model_name,
                    role="assistant",
                    content=missing_suffix,
                )
            else:
                yield _build_stream_chunk(
                    response_id, model_name, content=missing_suffix
                )
            streamed_content_accumulator += missing_suffix
        elif final_reply != streamed_content_accumulator:
            # text
            if not streamed_content_accumulator and final_reply:
                if not assistant_started:
                    assistant_started = True
                    yield _build_stream_chunk(
                        response_id,
                        model_name,
                        role="assistant",
                        content=final_reply,
                    )
                else:
                    yield _build_stream_chunk(
                        response_id, model_name, content=final_reply
                    )
                streamed_content_accumulator = final_reply

        metadata_event = _build_model_metadata_event(model_name, model_metadata)
        if metadata_event:
            yield metadata_event

        yield _build_stream_chunk(response_id, model_name, finish_reason="stop")
        yield "data: [DONE]\n\n"


def _create_standard_stream_generator(
    response_id: str,
    model_name: str,
    first_item: Any,
    stream_gen: Iterable[Any],
) -> Generator[str, None, None]:
    """
    Standard text SSE text

    text
    - thinking_chunk: text
    - thinking_replace: text
    - search_metadata: text
    - choices[0].delta.content: text
    """
    streamed_content_accumulator = ""
    streamed_thinking_accumulator = ""
    collected_search_sources = []
    collected_search_queries = []
    authoritative_final_content = ""
    authoritative_final_source_type = ""
    model_metadata: dict[str, Any] = {}
    assistant_started = False

    try:
        for raw_item in _iter_stream_items(first_item, stream_gen):
            item = _normalize_stream_item(raw_item)
            item_type = item.get("type")

            model_metadata = _merge_model_metadata(model_metadata, item)
            if item_type == "model_metadata":
                continue

            if item_type == "final_content":
                final_text = str(item.get("text", "") or "").strip()
                if final_text:
                    authoritative_final_content = final_text
                    authoritative_final_source_type = str(
                        item.get("source_type", "") or ""
                    )
                continue

            # Standard text thinkingtext thinking_chunk text
            if item_type == "thinking":
                thinking_text = item.get("text", "")
                if thinking_text:
                    streamed_thinking_accumulator += thinking_text
                    # text thinking_chunk text
                    yield f"data: {json.dumps({'type': 'thinking_chunk', 'text': thinking_text}, ensure_ascii=False)}\n\n"
                continue

            # Standard text searchtext
            if item_type == "search":
                search_data = item.get("data", {})
                if isinstance(search_data, dict):
                    # text queries text sources
                    queries = search_data.get("queries", [])
                    sources = search_data.get("sources", [])

                    if queries:
                        collected_search_queries.extend(queries)
                    if sources:
                        collected_search_sources.extend(sources)
                continue

            if item_type != "content":
                continue

            chunk_text = item.get("text", "")
            if not chunk_text:
                continue

            streamed_content_accumulator += chunk_text

            # text OpenAI text delta
            if not assistant_started:
                assistant_started = True
                yield _build_stream_chunk(
                    response_id,
                    model_name,
                    role="assistant",
                    content=chunk_text,
                )
            else:
                yield _build_stream_chunk(response_id, model_name, content=chunk_text)
    except asyncio.CancelledError:
        logger.info(
            "Standard streaming cancelled by client",
            extra={"request_info": {"event": "standard_stream_cancelled"}},
        )
        raise
    except Exception as exc:
        if _is_client_disconnect_error(exc):
            logger.info(
                "Standard streaming connection closed by client",
                extra={
                    "request_info": {"event": "standard_stream_client_disconnected"}
                },
            )
            return
        logger.error(
            "Standard streaming interrupted",
            exc_info=True,
            extra={"request_info": {"event": "standard_stream_interrupted"}},
        )
        error_hint = "\n\n[Upstream connection interrupted. Retry later.]"
        streamed_content_accumulator += error_hint
        if not assistant_started:
            assistant_started = True
            yield _build_stream_chunk(
                response_id,
                model_name,
                role="assistant",
                content=error_hint,
            )
        else:
            yield _build_stream_chunk(response_id, model_name, content=error_hint)
    finally:
        # text
        final_reply, _ = _select_best_final_reply(
            streamed_content_accumulator,
            authoritative_final_content,
            authoritative_final_source_type,
        )

        # text
        missing_suffix = _compute_missing_suffix(
            streamed_content_accumulator, final_reply
        )
        if missing_suffix:
            if not assistant_started:
                assistant_started = True
                yield _build_stream_chunk(
                    response_id,
                    model_name,
                    role="assistant",
                    content=missing_suffix,
                )
            else:
                yield _build_stream_chunk(
                    response_id, model_name, content=missing_suffix
                )
            streamed_content_accumulator += missing_suffix
        elif final_reply != streamed_content_accumulator:
            # text
            if not streamed_content_accumulator and final_reply:
                if not assistant_started:
                    assistant_started = True
                    yield _build_stream_chunk(
                        response_id,
                        model_name,
                        role="assistant",
                        content=final_reply,
                    )
                else:
                    yield _build_stream_chunk(
                        response_id, model_name, content=final_reply
                    )
                streamed_content_accumulator = final_reply

        # text search_metadata text
        if collected_search_sources or collected_search_queries:
            search_metadata = {
                "type": "search_metadata",
                "searches": {
                    "queries": collected_search_queries,
                    "sources": collected_search_sources,
                },
            }
            yield f"data: {json.dumps(search_metadata, ensure_ascii=False)}\n\n"

        metadata_event = _build_model_metadata_event(model_name, model_metadata)
        if metadata_event:
            yield metadata_event

        yield _build_stream_chunk(response_id, model_name, finish_reason="stop")
        yield "data: [DONE]\n\n"


def _persist_round(
    manager,
    background_tasks: BackgroundTasks,
    conversation_id: str,
    user_prompt: str,
    assistant_reply: str,
    assistant_thinking: str = "",
) -> None:
    """
    text

    text
    - text round >= WINDOW_ROUNDS//2 text
    - text BackgroundTasks text
    """
    round_index = manager.persist_round(
        conversation_id,
        user_prompt,
        assistant_reply,
        assistant_thinking=assistant_thinking,
    )

    # text
    window_rounds = 8  # text conversation.py text
    precompress_threshold = window_rounds // 2  # text 4 text

    if round_index >= precompress_threshold:
        # text
        round_to_compress = round_index - window_rounds + 1
        if round_to_compress >= 0:
            background_tasks.add_task(
                compress_sliding_window_round,
                manager=manager,
                conversation_id=conversation_id,
                round_number=round_to_compress,
            )
            logger.info(
                "Triggered async pre-compression",
                extra={
                    "request_info": {
                        "event": "async_precompress_triggered",
                        "conversation_id": conversation_id,
                        "current_round": round_index,
                        "compress_round": round_to_compress,
                    }
                },
            )

    # text
    background_tasks.add_task(
        compress_round_if_needed,
        manager=manager,
        conversation_id=conversation_id,
    )


def _persist_history_messages(
    manager, conversation_id: str, history_messages: List[Tuple[str, str, str]]
) -> None:
    for role, content, thinking in history_messages:
        manager.add_message(conversation_id, role, content, thinking)


def _is_client_disconnect_error(exc: BaseException) -> bool:
    if isinstance(exc, asyncio.CancelledError):
        return True
    if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
        return True
    if isinstance(exc, OSError):
        return exc.errno in {32, 54, 104, 10053, 10054}
    return False


def _request_state_attachments(request: Request) -> list[Any]:
    attachments = getattr(request.state, "attachments", None)
    if attachments is None:
        attachments = getattr(request.state, "_attachments", None)
    return attachments if isinstance(attachments, list) else []


def _attachment_error_response(exc: AttachmentError) -> JSONResponse:
    return _build_error_response(
        getattr(exc, "status_code", 400) or 400,
        code=getattr(exc, "code", "invalid_attachment") or "invalid_attachment",
        message=str(exc),
        error_type="invalid_request_error",
        param=getattr(exc, "param", "attachments") or "attachments",
    )


def _handle_lite_request(
    request: Request,
    req_body: ChatCompletionRequest,
    response: Response | None = None,
) -> JSONResponse | StreamingResponse | ChatCompletionResponse:
    """text Lite text"""
    pool = request.app.state.account_pool

    req_body.model = _resolve_request_model(req_body.model)
    assert req_body.model is not None

    # text
    cleaned_msgs, attachments = normalize_chat_messages([m.dict() for m in req_body.messages], getattr(req_body, "attachments", None))
    state_attachments = _request_state_attachments(request)
    if state_attachments:
        attachments = state_attachments
    # Gate feature flag
    policy = AttachmentPolicy.from_env()
    if attachments and not policy.enabled:
        openai_error("Attachments are disabled for this server.", "attachments_disabled")

    # text
    req_body.messages = [ChatMessage(**m) for m in cleaned_msgs]
    # text
    user_prompt = _prepare_messages_lite(req_body)

    response_id = f"chatcmpl-{uuid.uuid4().hex}"
    max_retries = max(3, len(pool.clients))

    for attempt in range(1, max_retries + 1):
        client = None
        try:
            client = pool.get_client()

            # Read poll configuration from headers if available
            poll_interval_hdr = request.headers.get("x-notion-poll-interval")
            poll_timeout_hdr = request.headers.get("x-notion-poll-timeout")
            if poll_interval_hdr:
                try:
                    client.poll_interval = float(poll_interval_hdr)
                except ValueError:
                    pass
            if poll_timeout_hdr:
                try:
                    client.poll_timeout = float(poll_timeout_hdr)
                except ValueError:
                    pass

            # text Lite transcripttext
            transcript = build_lite_transcript(user_prompt, req_body.model)

            # text Notion APItext thread_idtext
            persist_remote_chat = None
            if req_body.metadata and isinstance(req_body.metadata, dict):
                persist_remote_chat = req_body.metadata.get("persist_remote_chat")

            stream_gen = client.stream_response(
                transcript,
                thread_id=None,
                attachments=attachments if attachments else None,
                persist_remote_chat=persist_remote_chat,
            )
            first_item = next(stream_gen, None)

            if first_item is None:
                raise NotionUpstreamError(
                    "Notion upstream returned empty content.", retriable=True
                )

            # text
            if req_body.stream:
                stream_headers = {
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                }
                return StreamingResponse(
                    _create_lite_stream_generator(
                        response_id,
                        req_body.model,
                        first_item,
                        stream_gen,
                    ),
                    media_type="text/event-stream",
                    headers=stream_headers,
                )

            # text
            content_parts: list[str] = []
            authoritative_final_content = ""
            authoritative_final_source_type = ""
            model_metadata: dict[str, Any] = {}

            for raw_item in _iter_stream_items(first_item, stream_gen):
                item = _normalize_stream_item(raw_item)
                item_type = item.get("type")

                model_metadata = _merge_model_metadata(model_metadata, item)
                if item_type == "model_metadata":
                    continue

                if item_type == "final_content":
                    final_text = str(item.get("text", "") or "").strip()
                    if final_text:
                        authoritative_final_content = final_text
                        authoritative_final_source_type = str(
                            item.get("source_type", "") or ""
                        )
                    continue

                # Lite text thinking text search
                if item_type in ("thinking", "search"):
                    continue

                if item_type != "content":
                    continue

                chunk_text = item.get("text", "")
                if chunk_text:
                    content_parts.append(chunk_text)

            full_text, _ = _select_best_final_reply(
                "".join(content_parts),
                authoritative_final_content,
                authoritative_final_source_type,
            )

            if not full_text.strip():
                raise NotionUpstreamError(
                    "Notion upstream returned empty content.", retriable=True
                )

            response_text = (
                full_text if full_text.strip() else "[assistant_no_visible_content]"
            )
            response_obj = ChatCompletionResponse(
                id=response_id,
                model=req_body.model,
                choices=[
                    ChatMessageResponseChoice(
                        message=ChatMessage(role="assistant", content=response_text)
                    )
                ],
            )
            _attach_response_model_metadata(response_obj, req_body.model, model_metadata)
            return response_obj

        except NotionUpstreamError as exc:
            if client is not None and exc.retriable:
                pool.mark_failed(client)
            logger.warning(
                "Lite mode: Notion upstream failed",
                extra={
                    "request_info": {
                        "event": "lite_notion_upstream_failed",
                        "attempt": attempt,
                        "max_retries": max_retries,
                        "status_code": exc.status_code,
                        "retriable": exc.retriable,
                        "response_excerpt": exc.response_excerpt,
                    }
                },
            )
            if attempt == max_retries or not exc.retriable:
                return _upstream_error_response(exc)
        except RuntimeError as exc:
            logger.error(
                "Lite mode: No available client in account pool",
                extra={
                    "request_info": {
                        "event": "lite_account_pool_unavailable",
                        "detail": str(exc),
                    }
                },
            )
            return _build_error_response(
                503,
                code="POOL_COOLING",
                message=str(exc),
                error_type="account_pool_cooling",
                suggestion="Retry later.",
            )
        except AttachmentError as exc:
            logger.warning(
                "Lite mode: Invalid attachment input",
                extra={
                    "request_info": {
                        "event": "lite_invalid_attachment",
                        "code": getattr(exc, "code", "invalid_attachment"),
                        "param": getattr(exc, "param", "attachments"),
                    }
                },
            )
            return _attachment_error_response(exc)
        except HTTPException:
            raise
        except Exception:
            if client is not None:
                pool.mark_failed(client)
            logger.error(
                "Lite mode: Unhandled error",
                exc_info=True,
                extra={
                    "request_info": {
                        "event": "lite_unhandled_exception",
                        "attempt": attempt,
                    }
                },
            )
            if attempt == max_retries:
                return _build_error_response(
                    500,
                    code="INTERNAL_ERROR",
                    message="Service error.",
                    error_type="internal_error",
                    suggestion="Retry later.",
                )

    return _build_error_response(
        503,
        code="RETRIES_EXHAUSTED",
        message="Service error.",
        error_type="upstream_error",
        suggestion="Notion text",
    )


def _handle_standard_request(
    request: Request,
    req_body: ChatCompletionRequest,
    response: Response | None = None,
) -> JSONResponse | StreamingResponse | ChatCompletionResponse:
    """
    text Standard text thinking text

    text Lite text
    1. text messages text
    2. text thinking text
    3. text
    """
    from app.conversation import build_standard_transcript

    pool = request.app.state.account_pool

    req_body.model = _resolve_request_model(req_body.model)
    assert req_body.model is not None

    response_id = f"chatcmpl-{uuid.uuid4().hex}"
    max_retries = max(3, len(pool.clients))

    for attempt in range(1, max_retries + 1):
        client = None
        try:
            client = pool.get_client()

            # Read poll configuration from headers if available
            poll_interval_hdr = request.headers.get("x-notion-poll-interval")
            poll_timeout_hdr = request.headers.get("x-notion-poll-timeout")
            if poll_interval_hdr:
                try:
                    client.poll_interval = float(poll_interval_hdr)
                except ValueError:
                    pass
            if poll_timeout_hdr:
                try:
                    client.poll_timeout = float(poll_timeout_hdr)
                except ValueError:
                    pass

            # text
            cleaned_msgs, attachments = normalize_chat_messages([m.dict() for m in req_body.messages], getattr(req_body, "attachments", None))
            state_attachments = _request_state_attachments(request)
            if state_attachments:
                attachments = state_attachments
            policy = AttachmentPolicy.from_env()
            if attachments and not policy.enabled:
                openai_error("Attachments are disabled for this server.", "attachments_disabled")

            # text Standard transcripttext
            # text client text
            account = {
                "user_id": client.user_id,
                "space_id": client.space_id,
            }
            messages = cleaned_msgs
            transcript = build_standard_transcript(messages, req_body.model, account)

            # text Notion APItext thread_idtext Notion text
            persist_remote_chat = None
            if req_body.metadata and isinstance(req_body.metadata, dict):
                persist_remote_chat = req_body.metadata.get("persist_remote_chat")

            stream_gen = client.stream_response(
                transcript,
                thread_id=None,
                attachments=attachments if attachments else None,
                persist_remote_chat=persist_remote_chat,
            )
            first_item = next(stream_gen, None)

            if first_item is None:
                raise NotionUpstreamError(
                    "Notion upstream returned empty content.", retriable=True
                )

            # text
            if req_body.stream:
                stream_headers = {
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                }
                return StreamingResponse(
                    _create_standard_stream_generator(
                        response_id,
                        req_body.model,
                        first_item,
                        stream_gen,
                    ),
                    media_type="text/event-stream",
                    headers=stream_headers,
                )

            # text
            content_parts: list[str] = []
            thinking_parts: list[str] = []
            search_results: list[dict] = []
            authoritative_final_content = ""
            authoritative_final_source_type = ""
            model_metadata: dict[str, Any] = {}

            for raw_item in _iter_stream_items(first_item, stream_gen):
                item = _normalize_stream_item(raw_item)
                item_type = item.get("type")

                model_metadata = _merge_model_metadata(model_metadata, item)
                if item_type == "model_metadata":
                    continue

                if item_type == "final_content":
                    final_text = str(item.get("text", "") or "").strip()
                    if final_text:
                        authoritative_final_content = final_text
                        authoritative_final_source_type = str(
                            item.get("source_type", "") or ""
                        )
                    continue

                # Standard text thinking
                if item_type == "thinking":
                    thinking_text = item.get("text", "")
                    if thinking_text:
                        thinking_parts.append(thinking_text)
                    continue

                # Standard text search
                if item_type == "search":
                    search_data = item.get("data", {})
                    if search_data:
                        search_results.append(search_data)
                    continue

                if item_type != "content":
                    continue

                chunk_text = item.get("text", "")
                if chunk_text:
                    content_parts.append(chunk_text)

            full_text, _ = _select_best_final_reply(
                "".join(content_parts),
                authoritative_final_content,
                authoritative_final_source_type,
            )

            if not full_text.strip():
                raise NotionUpstreamError(
                    "Notion upstream returned empty content.", retriable=True
                )

            response_text = (
                full_text if full_text.strip() else "[assistant_no_visible_content]"
            )

            # text
            response_message = ChatMessage(role="assistant", content=response_text)

            # text thinkingtext
            if thinking_parts:
                response_message.thinking = "".join(thinking_parts)

            # text
            response_obj = ChatCompletionResponse(
                id=response_id,
                model=req_body.model,
                choices=[ChatMessageResponseChoice(message=response_message)],
            )
            _attach_response_model_metadata(response_obj, req_body.model, model_metadata)

            # text
            if search_results:
                # text queries text sources
                all_queries = []
                all_sources = []
                for result in search_results:
                    if isinstance(result, dict):
                        all_queries.extend(result.get("queries", []))
                        all_sources.extend(result.get("sources", []))

                if all_queries or all_sources:
                    # text
                    response_obj.search_metadata = {
                        "queries": all_queries,
                        "sources": all_sources,
                    }

            return response_obj

        except NotionUpstreamError as exc:
            if client is not None and exc.retriable:
                pool.mark_failed(client)
            logger.warning(
                "Standard mode: Notion upstream failed",
                extra={
                    "request_info": {
                        "event": "standard_notion_upstream_failed",
                        "attempt": attempt,
                        "max_retries": max_retries,
                        "status_code": exc.status_code,
                        "retriable": exc.retriable,
                        "response_excerpt": exc.response_excerpt,
                    }
                },
            )
            if attempt == max_retries or not exc.retriable:
                return _upstream_error_response(exc)
        except RuntimeError as exc:
            logger.error(
                "Standard mode: No available client in account pool",
                extra={
                    "request_info": {
                        "event": "standard_account_pool_unavailable",
                        "detail": str(exc),
                    }
                },
            )
            return _build_error_response(
                503,
                code="POOL_COOLING",
                message=str(exc),
                error_type="account_pool_cooling",
                suggestion="Retry later.",
            )
        except AttachmentError as exc:
            logger.warning(
                "Standard mode: Invalid attachment input",
                extra={
                    "request_info": {
                        "event": "standard_invalid_attachment",
                        "code": getattr(exc, "code", "invalid_attachment"),
                        "param": getattr(exc, "param", "attachments"),
                    }
                },
            )
            return _attachment_error_response(exc)
        except HTTPException:
            raise
        except Exception:
            if client is not None:
                pool.mark_failed(client)
            logger.error(
                "Standard mode: Unhandled error",
                exc_info=True,
                extra={
                    "request_info": {
                        "event": "standard_unhandled_exception",
                        "attempt": attempt,
                    }
                },
            )
            if attempt == max_retries:
                return _build_error_response(
                    500,
                    code="INTERNAL_ERROR",
                    message="Service error.",
                    error_type="internal_error",
                    suggestion="Retry later.",
                )

    return _build_error_response(
        503,
        code="RETRIES_EXHAUSTED",
        message="Service error.",
        error_type="upstream_error",
        suggestion="Notion text",
    )


@router.post("/chat/completions", tags=["chat"])
async def create_chat_completion(
    request: Request,
    req_body: ChatCompletionRequest,
    background_tasks: BackgroundTasks,
    response: Response,
):
    """
    text OpenAI APItext

    text
    - Lite text30/text
    - Standard text25/text thinking text
    - Heavy text20/text
    """
    from app.config import is_standard_mode

    req_body.model = _resolve_request_model(req_body.model)
    assert req_body.model is not None

    # Check for local smoke/preflight messages to avoid creating new chats in Notion.
    if req_body.messages:
        last_content = req_body.messages[-1].content or ""
        probe_response = _local_probe_response_text(last_content)
        if probe_response:
            response_id = f"chatcmpl-{uuid.uuid4().hex}"
            if req_body.stream:
                def ping_stream_generator() -> Generator[str, None, None]:
                    yield _build_stream_chunk(response_id, req_body.model, role="assistant")
                    yield _build_stream_chunk(response_id, req_body.model, content=probe_response)
                    yield _build_stream_chunk(response_id, req_body.model, finish_reason="stop")
                    yield "data: [DONE]\n\n"
                
                stream_headers = {
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                }
                return StreamingResponse(
                    ping_stream_generator(),
                    media_type="text/event-stream",
                    headers=stream_headers,
                )
            else:
                return ChatCompletionResponse(
                    id=response_id,
                    model=req_body.model,
                    choices=[
                        ChatMessageResponseChoice(
                            message=ChatMessage(role="assistant", content=probe_response)
                        )
                    ],
                )

    # Lite text
    if is_lite_mode():
        import anyio
        return await anyio.to_thread.run_sync(_handle_lite_request, request, req_body, response)

    # Standard text thinking text
    if is_standard_mode():
        import anyio
        return await anyio.to_thread.run_sync(_handle_standard_request, request, req_body, response)

    # Heavy text
    pool = request.app.state.account_pool
    manager = request.app.state.conversation_manager

    user_prompt, history_messages, raw_user_prompt = _prepare_messages(req_body)
    recall_query = (
        _extract_recall_query(raw_user_prompt)
        if _contains_recall_intent(raw_user_prompt)
        else None
    )

    conversation_id = req_body.conversation_id.strip() if req_body.conversation_id else ""
    restore_history = False
    if not conversation_id:
        conversation_id = manager.new_conversation()
        restore_history = True
    elif not manager.conversation_exists(conversation_id):
        logger.warning(
            "Conversation id not found, creating a fresh conversation",
            extra={
                "request_info": {
                    "event": "conversation_id_not_found",
                    "provided_conversation_id": conversation_id,
                }
            },
        )
        conversation_id = manager.new_conversation()
        restore_history = True

    # text
    # text conversation_id text
    if history_messages:
        # text
        with manager._get_conn() as conn:
            existing_count = manager._count_messages(conn, conversation_id)
            history_count = len(history_messages)

            # text
            # text
            # 1. text
            # 2. text
            # 3. text"text AI text"text bug
            if history_count > existing_count:
                _persist_history_messages(manager, conversation_id, history_messages)
                restored_user_count = sum(
                    1 for role, *_ in history_messages if role == "user"
                )
                restored_assistant_count = sum(
                    1 for role, *_ in history_messages if role == "assistant"
                )

                logger.info(
                    "Restored history into conversation",
                    extra={
                        "request_info": {
                            "event": "conversation_history_restored",
                            "conversation_id": conversation_id,
                            "restore_history_flag": restore_history,
                            "existing_count": existing_count,
                            "history_count": history_count,
                            "restored_total": len(history_messages),
                            "restored_user_count": restored_user_count,
                            "restored_assistant_count": restored_assistant_count,
                        }
                    },
                )

    response_id = f"chatcmpl-{uuid.uuid4().hex}"
    max_retries = max(3, len(pool.clients))

    for attempt in range(1, max_retries + 1):
        client = None
        try:
            client = pool.get_client()
            transcript_payload = manager.get_transcript_payload(
                notion_client=client,
                conversation_id=conversation_id,
                new_prompt=user_prompt,
                model_name=req_body.model,
                recall_query=recall_query,
            )
            transcript = transcript_payload["transcript"]
            memory_degraded = bool(transcript_payload.get("memory_degraded"))
            memory_headers = {"X-Memory-Status": "degraded"} if memory_degraded else {}

            # text thread_id text
            thread_id = manager.get_conversation_thread_id(conversation_id)

            # textNotion text thread text config text model
            # text thread text thread text transcript text modeltext
            # text thread text Notion text model text
            # text + text
            if thread_id:
                bound_model = manager.get_conversation_thread_model(conversation_id)
                # bound_model text None text
                # text thread text bugtext
                # text"text"text thread text
                if not bound_model or bound_model != req_body.model:
                    logger.info(
                        "Recreating Notion thread: model changed or legacy binding",
                        extra={
                            "request_info": {
                                "event": "thread_model_switched",
                                "conversation_id": conversation_id,
                                "old_model": bound_model,
                                "new_model": req_body.model,
                                "reason": "model_mismatch" if bound_model else "legacy_no_binding",
                            }
                        },
                    )
                    manager.clear_conversation_thread(conversation_id)
                    thread_id = None

            # Pass attachments when present
            _cleaned_msgs, attachments = normalize_chat_messages(
                [m.dict() for m in req_body.messages],
                getattr(req_body, "attachments", None),
            )
            state_attachments = _request_state_attachments(request)
            if state_attachments:
                attachments = state_attachments
            if attachments and not AttachmentPolicy.from_env().enabled:
                openai_error("Attachments are disabled for this server.", "attachments_disabled")

            persist_remote_chat = None
            if req_body.metadata and isinstance(req_body.metadata, dict):
                persist_remote_chat = req_body.metadata.get("persist_remote_chat")

            stream_gen = client.stream_response(
                transcript,
                thread_id=thread_id,
                attachments=attachments if attachments else None,
                persist_remote_chat=persist_remote_chat,
            )
            first_item = next(stream_gen, None)

            # text thread_idtext
            if not thread_id and hasattr(client, "current_thread_id"):
                manager.set_conversation_thread_id(
                    conversation_id,
                    client.current_thread_id,
                    model_name=req_body.model,
                )

            if first_item is None:
                raise NotionUpstreamError(
                    "Notion upstream returned empty content.", retriable=True
                )

            first_stream_item = first_item
            active_stream_gen = stream_gen
            attempt_no = attempt
            active_client = client

            def openai_stream_generator(
                first_stream_item: Any = first_stream_item,
                active_stream_gen: Any = active_stream_gen,
                attempt_no: int = attempt_no,
                active_client: Any = active_client,
            ) -> Generator[str, None, None]:
                streamed_content_accumulator = ""
                thinking_accumulator = ""
                authoritative_final_content = ""
                authoritative_final_source_type = ""
                assistant_started = False
                pending_search_md = ""
                client_type = request.headers.get("X-Client-Type", "").lower()
                recent_thinking_buffer: list[str] = []

                try:
                    for raw_item in _iter_stream_items(first_stream_item, active_stream_gen):
                        item = _normalize_stream_item(raw_item)
                        item_type = item.get("type")

                        if item_type == "search":
                            search_data = item.get("data")
                            if isinstance(search_data, dict) and search_data:
                                pending_search_md += _format_search_results_md(
                                    search_data
                                )
                                if client_type == "web":
                                    yield _build_local_ui_chunk(
                                        response_id,
                                        req_body.model,
                                        "search_metadata",
                                        searches=search_data,
                                    )
                            continue

                        if item_type == "final_content":
                            final_text = str(item.get("text", "") or "").strip()
                            if final_text:
                                authoritative_final_content = final_text
                                authoritative_final_source_type = str(
                                    item.get("source_type", "") or ""
                                )
                            continue

                        if item_type == "thinking":
                            thinking_text = item.get("text", "")
                            if thinking_text:
                                thinking_accumulator += thinking_text
                                # Track recent thinking for overlap detection
                                recent_thinking_buffer.append(thinking_text)
                                # Keep buffer manageable (max 40 recent chunks)
                                if len(recent_thinking_buffer) > 40:
                                    recent_thinking_buffer.pop(0)

                                if not assistant_started:
                                    assistant_started = True
                                    yield _build_stream_chunk(
                                        response_id,
                                        req_body.model,
                                        role="assistant",
                                        thinking=thinking_text,
                                    )
                                else:
                                    yield _build_stream_chunk(
                                        response_id,
                                        req_body.model,
                                        thinking=thinking_text,
                                    )
                            continue

                        if item_type != "content":
                            continue

                        chunk_text = item.get("text", "")
                        if not chunk_text and not pending_search_md:
                            continue

                        # Check if content overlaps with recent thinking (prevents thinking leakage)
                        if recent_thinking_buffer and chunk_text.strip():
                            combined_recent_thinking = "".join(recent_thinking_buffer)
                            chunk_normalized = chunk_text.strip()

                            # Use normalized text without spaces for robust comparison
                            combined_norm = re.sub(r"\s+", "", combined_recent_thinking)
                            chunk_norm = re.sub(r"\s+", "", chunk_normalized)

                            # Check for significant overlap - skip duplicate content
                            # We only skip if a sufficiently long chunk matches to avoid swallowing short common characters.
                            if (
                                chunk_norm
                                and len(chunk_norm) > 3
                                and (
                                    chunk_norm in combined_norm
                                    or (
                                        len(chunk_norm) > 10
                                        and chunk_norm[:10] in combined_norm
                                    )
                                )
                            ):
                                # Skip this chunk as it's likely duplicated thinking content
                                logger.debug(
                                    "Skipping duplicate content chunk that overlaps with thinking",
                                    extra={
                                        "request_info": {
                                            "event": "content_overlap_with_thinking",
                                            "chunk_length": len(chunk_text),
                                            "overlap_detected": True,
                                        }
                                    },
                                )
                                continue

                        # text
                        if pending_search_md and client_type != "web":
                            chunk_text = pending_search_md + chunk_text

                        if pending_search_md:
                            pending_search_md = ""

                        streamed_content_accumulator += chunk_text
                        if not assistant_started:
                            assistant_started = True
                            yield _build_stream_chunk(
                                response_id,
                                req_body.model,
                                role="assistant",
                                content=chunk_text,
                            )
                        else:
                            yield _build_stream_chunk(
                                response_id, req_body.model, content=chunk_text
                            )
                except asyncio.CancelledError:
                    logger.info(
                        "Streaming response cancelled by downstream client",
                        extra={
                            "request_info": {
                                "event": "stream_cancelled_by_client",
                                "conversation_id": conversation_id,
                                "attempt": attempt_no,
                            }
                        },
                    )
                    raise
                except Exception as exc:
                    if _is_client_disconnect_error(exc):
                        logger.info(
                            "Streaming connection closed by downstream client",
                            extra={
                                "request_info": {
                                    "event": "stream_client_disconnected",
                                    "conversation_id": conversation_id,
                                    "attempt": attempt_no,
                                }
                            },
                        )
                        return
                    if isinstance(exc, NotionUpstreamError) and active_client is not None and getattr(exc, 'retriable', False):
                        pool.mark_failed(active_client)
                    log_method = (
                        logger.warning
                        if isinstance(exc, NotionUpstreamError)
                        else logger.error
                    )
                    log_method(
                        "Streaming response interrupted",
                        exc_info=True,
                        extra={
                            "request_info": {
                                "event": "stream_interrupted",
                                "conversation_id": conversation_id,
                                "attempt": attempt_no,
                                "is_upstream_error": isinstance(
                                    exc, NotionUpstreamError
                                ),
                            }
                        },
                    )
                    error_hint = "\n\n[Upstream connection interrupted. Retry later.]"
                    streamed_content_accumulator += error_hint
                    if not assistant_started:
                        assistant_started = True
                        yield _build_stream_chunk(
                            response_id,
                            req_body.model,
                            role="assistant",
                            content=error_hint,
                        )
                    else:
                        yield _build_stream_chunk(
                            response_id, req_body.model, content=error_hint
                        )
                finally:
                    final_reply, reply_decision = _select_best_final_reply(
                        streamed_content_accumulator,
                        authoritative_final_content,
                        authoritative_final_source_type,
                    )

                    missing_suffix = _compute_missing_suffix(
                        streamed_content_accumulator, final_reply
                    )
                    if missing_suffix:
                        suffix_to_emit = missing_suffix
                        if (
                            pending_search_md
                            and client_type != "web"
                            and not streamed_content_accumulator
                        ):
                            suffix_to_emit = pending_search_md + suffix_to_emit
                            pending_search_md = ""
                        if not assistant_started:
                            assistant_started = True
                            yield _build_stream_chunk(
                                response_id,
                                req_body.model,
                                role="assistant",
                                content=suffix_to_emit,
                            )
                        else:
                            yield _build_stream_chunk(
                                response_id, req_body.model, content=suffix_to_emit
                            )
                        streamed_content_accumulator += suffix_to_emit
                    elif final_reply != streamed_content_accumulator:
                        # Diverged bodies cannot be safely "patched" in plain OpenAI deltas.
                        # Web client supports replace event to keep rendered body aligned with persisted final reply.
                        if client_type == "web":
                            yield _build_local_ui_chunk(
                                response_id,
                                req_body.model,
                                "content_replace",
                                content=final_reply,
                                source_type=authoritative_final_source_type,
                                decision=reply_decision,
                            )
                            streamed_content_accumulator = final_reply
                        elif not streamed_content_accumulator and final_reply:
                            # Non-web fallback when nothing has been shown yet.
                            emit_text = final_reply
                            if pending_search_md and client_type != "web":
                                emit_text = pending_search_md + emit_text
                                pending_search_md = ""
                            if not assistant_started:
                                assistant_started = True
                                yield _build_stream_chunk(
                                    response_id,
                                    req_body.model,
                                    role="assistant",
                                    content=emit_text,
                                )
                            else:
                                yield _build_stream_chunk(
                                    response_id, req_body.model, content=emit_text
                                )
                            streamed_content_accumulator = final_reply

                    thinking_replacement = _build_thinking_replacement(
                        streamed_content_accumulator,
                        thinking_accumulator,
                        final_reply,
                        authoritative_final_source_type,
                    )
                    if client_type == "web" and thinking_replacement is not None:
                        yield _build_local_ui_chunk(
                            response_id,
                            req_body.model,
                            "thinking_replace",
                            thinking=thinking_replacement["thinking"],
                            decision=thinking_replacement["decision"],
                            overlap_ratio=thinking_replacement["overlap_ratio"],
                            source_type=thinking_replacement["source_type"],
                            reply_decision=reply_decision,
                        )

                    persisted_thinking = (
                        str(thinking_replacement["thinking"])
                        if thinking_replacement is not None
                        else thinking_accumulator
                    )
                    if final_reply.strip() or persisted_thinking.strip():
                        try:
                            _persist_round(
                                manager,
                                background_tasks,
                                conversation_id,
                                user_prompt,
                                final_reply,
                                persisted_thinking,
                            )
                        except Exception:
                            logger.error(
                                "Failed to persist conversation round",
                                exc_info=True,
                                extra={
                                    "request_info": {
                                        "event": "conversation_persist_failed",
                                        "conversation_id": conversation_id,
                                    }
                                },
                            )
                    yield _build_stream_chunk(
                        response_id, req_body.model, finish_reason="stop"
                    )
                    yield "data: [DONE]\n\n"

            if req_body.stream:
                stream_headers = {
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                    "X-Conversation-Id": conversation_id,
                    **memory_headers,
                }
                return StreamingResponse(
                    openai_stream_generator(),
                    media_type="text/event-stream",
                    headers=stream_headers,
                )

            content_parts: list[str] = []
            thinking_parts: list[str] = []
            authoritative_final_content = ""
            authoritative_final_source_type = ""
            for raw_item in _iter_stream_items(first_item, stream_gen):
                item = _normalize_stream_item(raw_item)
                item_type = item.get("type")
                if item_type == "final_content":
                    final_text = str(item.get("text", "") or "").strip()
                    if final_text:
                        authoritative_final_content = final_text
                        authoritative_final_source_type = str(
                            item.get("source_type", "") or ""
                        )
                    continue
                if item_type == "thinking":
                    thinking_text = str(item.get("text", "") or "")
                    if thinking_text:
                        thinking_parts.append(thinking_text)
                    continue
                if item_type != "content":
                    continue
                chunk_text = item.get("text", "")
                if chunk_text:
                    content_parts.append(chunk_text)

            full_text, _ = _select_best_final_reply(
                "".join(content_parts),
                authoritative_final_content,
                authoritative_final_source_type,
            )
            merged_thinking = "".join(thinking_parts).strip()
            if not full_text.strip() and not merged_thinking:
                raise NotionUpstreamError(
                    "Notion upstream returned empty content.", retriable=True
                )

            _persist_round(
                manager,
                background_tasks,
                conversation_id,
                user_prompt,
                full_text,
                merged_thinking,
            )
            response.headers["X-Conversation-Id"] = conversation_id
            if memory_degraded:
                response.headers["X-Memory-Status"] = "degraded"

            response_text = (
                full_text if full_text.strip() else "[assistant_no_visible_content]"
            )
            return ChatCompletionResponse(
                id=response_id,
                model=req_body.model,
                choices=[
                    ChatMessageResponseChoice(
                        message=ChatMessage(role="assistant", content=response_text)
                    )
                ],
            )
        except NotionUpstreamError as exc:
            if client is not None and exc.retriable:
                pool.mark_failed(client)
            logger.warning(
                "Notion upstream failed",
                extra={
                    "request_info": {
                        "event": "notion_upstream_failed",
                        "attempt": attempt,
                        "max_retries": max_retries,
                        "conversation_id": conversation_id,
                        "status_code": exc.status_code,
                        "retriable": exc.retriable,
                        "response_excerpt": exc.response_excerpt,
                    }
                },
            )
            if attempt == max_retries or not exc.retriable:
                return _upstream_error_response(exc)
        except RuntimeError as exc:
            logger.error(
                "No available client in account pool",
                extra={
                    "request_info": {
                        "event": "account_pool_unavailable",
                        "detail": str(exc),
                    }
                },
            )
            return _build_error_response(
                503,
                code="POOL_COOLING",
                message=str(exc),
                error_type="account_pool_cooling",
                suggestion="Retry later.",
            )
        except AttachmentError as exc:
            logger.warning(
                "Invalid attachment input",
                extra={
                    "request_info": {
                        "event": "chat_completion_invalid_attachment",
                        "code": getattr(exc, "code", "invalid_attachment"),
                        "param": getattr(exc, "param", "attachments"),
                    }
                },
            )
            return _attachment_error_response(exc)
        except HTTPException:
            raise
        except Exception:
            if client is not None:
                pool.mark_failed(client)
            logger.error(
                "Unhandled chat completion error",
                exc_info=True,
                extra={
                    "request_info": {
                        "event": "chat_completion_unhandled_exception",
                        "attempt": attempt,
                        "conversation_id": conversation_id,
                    }
                },
            )
            if attempt == max_retries:
                return _build_error_response(
                    500,
                    code="INTERNAL_ERROR",
                    message="Service error.",
                    error_type="internal_error",
                    suggestion="Retry later.",
                )

    return _build_error_response(
        503,
        code="RETRIES_EXHAUSTED",
        message="Service error.",
        error_type="upstream_error",
        suggestion="Notion text",
    )


@router.delete("/conversations/{conversation_id}", tags=["chat"])
async def delete_conversation(conversation_id: str, request: Request):
    """
    Delete a conversation by its ID.
    """
    manager = request.app.state.conversation_manager
    deleted = manager.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"id": conversation_id, "deleted": True}
