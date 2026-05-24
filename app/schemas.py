import time
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

# ================================
# 请求相关 Schema (Chat Completion)
# ================================


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

    Attachment handling note:
    - Keep top-level `attachments` separate from `messages` at the schema layer.
    - app.attachments.normalizer.normalize_chat_messages() is the single canonical
      place that merges/normalizes structured content parts and top-level attachments.
    - Mutating attachments into the last user message here caused heavy-mode code to
      see a hybrid request before normalization, which could duplicate screenshot/file
      content across message preparation, persistence, and upstream dispatch.
    """
    model: str = Field(default="", description="Requested model.")
    messages: List[ChatMessage]
    stream: bool = Field(default=False, description="Whether to stream the response as SSE.")
    temperature: Optional[float] = Field(default=None, description="Sampling temperature.")
    conversation_id: Optional[str] = Field(default=None, description="Extension for stateful conversation tracking.")
    attachments: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Optional attachment descriptors. Normalized by the chat handler.",
    )

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
    content: Optional[str] = None
    role: Optional[str] = None

class ChatCompletionChunkChoice(BaseModel):
    index: int = 0
    delta: ChatCompletionChunkDelta
    finish_reason: Optional[str] = None

class ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: List[ChatCompletionChunkChoice]
