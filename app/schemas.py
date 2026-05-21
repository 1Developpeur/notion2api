import time
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

# ================================
# 请求相关 Schema (Chat Completion)
# ================================


def _attachment_to_content_part(item: Any) -> Any:
    """Normalize a top-level attachment object into an OpenAI-style content part."""
    if not isinstance(item, dict):
        return item
    if item.get("type"):
        return item
    normalized = dict(item)
    content_type = str(
        normalized.get("content_type")
        or normalized.get("mime_type")
        or ""
    ).lower()
    if content_type.startswith("image/") or normalized.get("image_url"):
        normalized["type"] = "image_url"
    else:
        normalized["type"] = "file"
    return normalized


class ChatMessage(BaseModel):
    """单条对话消息"""
    role: Literal["user", "assistant", "system"]
    # OpenAI-compatible clients may send either plain text or structured content
    # parts such as input_text, image_url, input_image, file, input_file.
    content: Any
    thinking: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    """
    OpenAI-Compatible 发起完成请求的 Payload。
    保留 `conversation_id` 作为特定的扩展字段，若缺失则视为独立请求。
    """
    model: str = Field(default="", description="Requested model.")
    messages: List[ChatMessage]
    stream: bool = Field(default=False, description="Whether to stream the response as SSE.")
    temperature: Optional[float] = Field(default=None, description="Sampling temperature.")
    conversation_id: Optional[str] = Field(default=None, description="Extension for stateful conversation tracking.")
    attachments: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Optional attachment descriptors. Merged into the last user message.",
    )

    def __init__(self, **data: Any):
        super().__init__(**data)
        if not self.attachments:
            return
        attachment_parts = [_attachment_to_content_part(item) for item in self.attachments]
        if not attachment_parts:
            return
        for msg in reversed(self.messages):
            if msg.role != "user":
                continue
            if isinstance(msg.content, list):
                msg.content = [*msg.content, *attachment_parts]
            elif msg.content in (None, ""):
                msg.content = attachment_parts
            else:
                msg.content = [{"type": "text", "text": str(msg.content)}, *attachment_parts]
            break

# ================================
# 非流式返回 Schema
# ================================

class ChatMessageResponseChoice(BaseModel):
    """非流式响应的选项"""
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"

class ChatCompletionResponse(BaseModel):
    """
    OpenAI-Compatible 完整返回 Payload。
    """
    id: str
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: List[ChatMessageResponseChoice]
    usage: Dict[str, int] = Field(
        default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    )
    # Standard 模式扩展字段
    search_metadata: Optional[Dict[str, Any]] = Field(default=None)

# ================================
# 流式返回 Schema (供内部组织)
# ================================

class ChatCompletionChunkDelta(BaseModel):
    """SSE Delta Block"""
    content: Optional[str] = None
    role: Optional[str] = None

class ChatCompletionChunkChoice(BaseModel):
    """SSE Choice Block"""
    index: int = 0
    delta: ChatCompletionChunkDelta
    finish_reason: Optional[str] = None

class ChatCompletionChunk(BaseModel):
    """
    OpenAI-Compatible 流式 Chunk
    """
    id: str
    object: str = "chat.completion.chunk"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: List[ChatCompletionChunkChoice]