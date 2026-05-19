from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.chat import create_chat_completion
from app.schemas import ChatCompletionRequest, ChatMessage

router = APIRouter()


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                item_type = str(item.get("type") or "")
                if item_type in {"input_text", "output_text", "text"}:
                    parts.append(str(item.get("text") or ""))
                elif "text" in item:
                    parts.append(str(item.get("text") or ""))
        return "\n".join(part for part in parts if part)
    return ""


def _responses_input_to_messages(input_value: Any) -> list[ChatMessage]:
    if isinstance(input_value, str):
        return [ChatMessage(role="user", content=input_value)]

    if not isinstance(input_value, list):
        raise HTTPException(status_code=400, detail="Responses API input must be a string or list.")

    messages: list[ChatMessage] = []
    for item in input_value:
        if isinstance(item, str):
            messages.append(ChatMessage(role="user", content=item))
            continue
        if not isinstance(item, dict):
            continue

        role = str(item.get("role") or "user")
        if role not in {"system", "user", "assistant"}:
            role = "user"

        if item.get("type") == "message" and "content" in item:
            text = _content_to_text(item.get("content"))
        elif "content" in item:
            text = _content_to_text(item.get("content"))
        elif item.get("type") in {"input_text", "output_text", "text"}:
            text = str(item.get("text") or "")
        else:
            text = ""

        if text.strip():
            messages.append(ChatMessage(role=role, content=text))

    if not messages:
        raise HTTPException(status_code=400, detail="Responses API input did not contain any text messages.")
    return messages


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return {}


def _chat_completion_to_response(chat_payload: dict[str, Any], requested_model: str) -> dict[str, Any]:
    choice = (chat_payload.get("choices") or [{}])[0] or {}
    message = choice.get("message") or {}
    text = str(message.get("content") or "")
    model = str(chat_payload.get("model") or requested_model)
    created = int(chat_payload.get("created") or time.time())
    response_id = f"resp_{uuid.uuid4().hex}"
    message_id = f"msg_{uuid.uuid4().hex}"

    return {
        "id": response_id,
        "object": "response",
        "created_at": created,
        "status": "completed",
        "model": model,
        "output": [
            {
                "id": message_id,
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": text,
                        "annotations": [],
                    }
                ],
            }
        ],
        "output_text": text,
        "usage": chat_payload.get("usage") or {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    }


@router.post("/responses", tags=["responses"])
async def create_response(
    request: Request,
    payload: dict[str, Any],
    background_tasks: BackgroundTasks,
    response: Response,
):
    """Minimal OpenAI Responses API compatibility shim backed by /v1/chat/completions."""
    model = str(payload.get("model") or "claude-opus4.6")
    messages = _responses_input_to_messages(payload.get("input"))
    stream = bool(payload.get("stream", False))

    chat_req = ChatCompletionRequest(
        model=model,
        messages=messages,
        stream=stream,
        temperature=payload.get("temperature"),
        conversation_id=payload.get("conversation_id"),
    )

    chat_result = await create_chat_completion(request, chat_req, background_tasks, response)

    if isinstance(chat_result, (JSONResponse, StreamingResponse)):
        return chat_result

    chat_payload = _as_dict(chat_result)
    return _chat_completion_to_response(chat_payload, model)
