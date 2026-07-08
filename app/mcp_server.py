from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Literal, Annotated

import httpx
from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()

DEFAULT_BASE_URL = "http://127.0.0.1:8120"
DEFAULT_MCP_HOST = "127.0.0.1"
DEFAULT_MCP_PORT = 8130
DEFAULT_MCP_PATH = "/mcp"
DEFAULT_TIMEOUT_SECONDS = 900.0
DEFAULT_MODEL = "claude-opus4.8"
DEFAULT_SESSION_NAME = "op"
DEFAULT_SESSION_STATE_PATH = Path(
    os.getenv(
        "MCP_NOTION2API_SESSION_STATE",
        str(Path.cwd() / ".notion2api_mcp_sessions.json"),
    )
)
DEFAULT_CHAT_JOB_STATE_PATH = Path(
    os.getenv(
        "MCP_NOTION2API_CHAT_JOB_STATE",
        str(DEFAULT_SESSION_STATE_PATH.with_name(".notion2api_mcp_chat_jobs.json")),
    )
)
DEFAULT_CHAT_WAIT_SECONDS = 45.0
MAX_CHAT_WAIT_SECONDS = 50.0
_CHAT_JOB_STATE_MUTEX = threading.RLock()
_CHAT_JOB_TASKS: dict[str, asyncio.Task[dict[str, Any]]] = {}
logger = logging.getLogger(__name__)
CHAT_JOB_STATE_WRITE_RETRIES = 5
CHAT_JOB_STATE_WRITE_BACKOFF_SECONDS = 0.05


class HealthOutput(BaseModel):
    ok: bool = Field(description="Whether the backend health call succeeded.")
    status_code: int | None = Field(default=None, description="HTTP status code returned by Notion2API.")
    status: str | None = Field(default=None, description="Backend status string, usually ok.")
    accounts: int | None = Field(default=None, description="Ready account count reported by Notion2API.")
    accounts_total: int | None = Field(default=None, description="Total configured account count.")
    accounts_cooling: int | None = Field(default=None, description="Number of accounts currently cooling down.")
    uptime: int | float | None = Field(default=None, description="Backend uptime, if reported.")
    raw: dict[str, Any] = Field(default_factory=dict, description="Raw backend health response.")


class ModelInfo(BaseModel):
    id: str = Field(description="Model id.")
    object: str | None = Field(default=None, description="OpenAI-style object type, usually model.")
    created: int | None = Field(default=None, description="Creation timestamp, if supplied.")
    owned_by: str | None = Field(default=None, description="Provider or owner, if supplied.")


class ListModelsOutput(BaseModel):
    ok: bool = Field(description="Whether the models call succeeded.")
    status_code: int | None = Field(default=None, description="HTTP status code returned by Notion2API.")
    count: int = Field(default=0, description="Number of model entries returned.")
    models: list[ModelInfo] = Field(default_factory=list, description="JSON-safe OpenAI-style model entries.")
    error: str | None = Field(default=None, description="Error summary if the backend did not return models.")


class ChatOutput(BaseModel):
    ok: bool = Field(description="Whether the model call succeeded.")
    status_code: int | None = Field(default=None, description="HTTP status code returned by Notion2API.")
    model: str = Field(description="Requested model id passed through the MCP wrapper.")
    actual_model: str = Field(default="", description="Actual Notion model/provider route used, if returned.")
    model_metadata: dict[str, Any] | None = Field(default=None, description="Notion2API model metadata, if any.")
    requested_model: str = Field(default="", description="Requested model id originally passed to the MCP wrapper.")
    backend_base_url: str = Field(default="", description="Canonical Notion2API backend URL used by this MCP wrapper.")
    timeout_seconds: float | None = Field(default=None, description="HTTP timeout used by the MCP wrapper for backend calls.")
    session_state_path: str = Field(default="", description="Path to the MCP session state file.")
    local_conversations_db: str = Field(default="", description="Expected local Notion2API conversations DB path.")
    imported_history_db: str = Field(default="", description="Expected imported Notion history DB path.")
    session_name: str | None = Field(default=None, description="Normalized MCP session name.")
    conversation_id: str | None = Field(default=None, description="Stable Notion2API conversation id used for the request.")
    session_created: bool | None = Field(default=None, description="True when the wrapper created a new MCP conversation binding.")
    status: str = Field(default="completed", description="MCP wrapper job status: completed, pending, running, error, or stale.")
    request_id: str | None = Field(default=None, description="Idempotency key used to deduplicate or poll this MCP chat request.")
    job_id: str | None = Field(default=None, description="Pollable job id. Currently identical to request_id.")
    retry_safe: bool = Field(default=False, description="True when retrying with the same request_id is safe and will not resubmit.")
    wait_seconds: float | None = Field(default=None, description="Bounded wait used before returning pending.")
    poll_hint: str = Field(default="", description="Human-readable polling instruction for pending or stale jobs.")
    error: str | None = Field(default=None, description="Error summary if the backend call failed or the job became stale.")
    response_text: str = Field(default="", description="Extracted assistant response text.")
    raw: dict[str, Any] = Field(default_factory=dict, description="Raw backend response.")


class ResponsesOutput(BaseModel):
    ok: bool = Field(description="Whether the responses endpoint call succeeded.")
    status_code: int | None = Field(default=None, description="HTTP status code returned by Notion2API.")
    model: str = Field(description="Requested model id passed through the MCP wrapper.")
    actual_model: str = Field(default="", description="Actual Notion model/provider route used, if returned.")
    model_metadata: dict[str, Any] | None = Field(default=None, description="Notion2API model metadata, if any.")
    requested_model: str = Field(default="", description="Requested model id originally passed to the MCP wrapper.")
    backend_base_url: str = Field(default="", description="Canonical Notion2API backend URL used by this MCP wrapper.")
    timeout_seconds: float | None = Field(default=None, description="HTTP timeout used by the MCP wrapper for backend calls.")
    session_state_path: str = Field(default="", description="Path to the MCP session state file.")
    local_conversations_db: str = Field(default="", description="Expected local Notion2API conversations DB path.")
    imported_history_db: str = Field(default="", description="Expected imported Notion history DB path.")
    response_text: str = Field(default="", description="Extracted response output text.")
    raw: dict[str, Any] = Field(default_factory=dict, description="Raw backend response.")


class ListSessionsOutput(BaseModel):
    ok: bool = Field(default=True, description="Whether the session listing succeeded.")
    count: int = Field(description="Number of known MCP sessions.")
    default_session: str = Field(description="Default session name used by OP calls.")
    state_path: str = Field(description="Path to the MCP session state file.")
    sessions: list[dict[str, str]] = Field(default_factory=list, description="Known named MCP session bindings.")


class SessionActionOutput(BaseModel):
    ok: bool = Field(description="Whether the session operation succeeded.")
    action: str = Field(description="Operation performed: reset or rename.")
    session_name: str = Field(description="Normalized target session name.")
    conversation_id: str = Field(description="Conversation id now bound to the target session.")
    previous_session_name: str | None = Field(default=None, description="Previous session name for rename operations.")
    previous_conversation_id: str | None = Field(default=None, description="Prior conversation id replaced or renamed, if any.")
    overwritten: bool = Field(default=False, description="Whether an existing target session was overwritten.")
    state_path: str = Field(description="Path to the MCP session state file.")


class MessagesOutput(BaseModel):
    ok: bool = Field(description="Whether local conversation messages were read successfully.")
    session_name: str = Field(default="", description="Normalized MCP session name used for lookup.")
    conversation_id: str = Field(default="", description="Resolved conversation id.")
    count: int = Field(default=0, description="Number of returned messages.")
    total_count: int = Field(default=0, description="Total local message count for the conversation.")
    db_path: str = Field(default="", description="Local Notion2API conversations database path.")
    messages: list[dict[str, Any]] = Field(default_factory=list, description="Messages in chronological order.")
    error: str | None = Field(default=None, description="Error summary if messages could not be read.")


class LastResponseOutput(BaseModel):
    ok: bool = Field(description="Whether the local last-response lookup completed.")
    found: bool = Field(default=False, description="Whether an assistant response was found.")
    session_name: str = Field(default="", description="Normalized MCP session name used for lookup.")
    conversation_id: str = Field(default="", description="Resolved conversation id.")
    response_text: str = Field(default="", description="Latest assistant visible response content.")
    message: dict[str, Any] | None = Field(default=None, description="Latest assistant message record, if found.")
    db_path: str = Field(default="", description="Local Notion2API conversations database path.")
    error: str | None = Field(default=None, description="Error summary if lookup failed.")


class ChatJobOutput(BaseModel):
    ok: bool = Field(description="Whether the chat job lookup completed.")
    found: bool = Field(default=False, description="Whether a job with this request_id exists.")
    status: str = Field(default="", description="Persisted job status: running, completed, error, or stale.")
    request_id: str = Field(default="", description="Idempotency key / job id.")
    job_id: str = Field(default="", description="Pollable job id. Currently identical to request_id.")
    session_name: str = Field(default="", description="Normalized MCP session name.")
    conversation_id: str = Field(default="", description="Conversation id associated with the job.")
    model: str = Field(default="", description="Requested model for the job.")
    endpoint: str = Field(default="", description="Backend endpoint used by the job.")
    created_at: int = Field(default=0, description="Unix epoch milliseconds when the job was created.")
    updated_at: int = Field(default=0, description="Unix epoch milliseconds when the job was last updated.")
    response_text: str = Field(default="", description="Completed assistant response text, if available.")
    response: dict[str, Any] | None = Field(default=None, description="Persisted ChatOutput-compatible response, if available.")
    error: str | None = Field(default=None, description="Persisted error summary, if any.")
    raw_job: dict[str, Any] = Field(default_factory=dict, description="Raw persisted job state.")
    last_response: dict[str, Any] | None = Field(default=None, description="Optional latest local assistant response lookup.")



def prepare_mcp_file_attachments(
    files: list[str] | None,
) -> list[dict[str, Any]]:
    if not files:
        return []

    from app.attachments.errors import AttachmentError
    from app.attachments.security import AttachmentPolicy, validate_attachment_count, validate_content_type, validate_size
    import mimetypes
    import base64
    from pathlib import Path

    policy = AttachmentPolicy.from_env()
    if not policy.enabled:
        raise AttachmentError(
            "Attachments are disabled for this server.",
            code="attachments_disabled",
            param="attachments",
        )

    validate_attachment_count(len(files), policy)

    prepared = []
    for file_path in files:
        path = Path(file_path)
        if not path.exists():
            raise AttachmentError(
                f"Attachment path does not exist: {file_path}",
                code="attachment_not_found",
                param="attachments",
            )
        if not path.is_file():
            raise AttachmentError(
                f"Attachment path is not a file: {file_path}",
                code="invalid_attachment_type",
                param="attachments",
            )

        size = path.stat().st_size
        validate_size(size, policy)

        guessed_type, _ = mimetypes.guess_type(path.name)
        if path.suffix.lower() == ".zip":
            guessed_type = "application/zip"
        elif path.suffix.lower() == ".csv":
            guessed_type = "text/csv"
        mime_type = validate_content_type(guessed_type or "application/octet-stream", policy)

        data = path.read_bytes()
        encoded = base64.b64encode(data).decode("utf-8")
        prepared.append({
            "name": path.name,
            "content_type": mime_type,
            "size_bytes": size,
            "source": "mcp_file",
            "data": f"data:{mime_type};base64,{encoded}",
        })

    return prepared


FileAttachments = Annotated[
    list[str] | None,
    Field(
        default=None,
        description="Files to attach to this request.",
        json_schema_extra={
            "items": {
                "type": "string",
                "format": "file",
            }
        },
    ),
]


class Notion2APIClient:
    """Small HTTP client used by MCP tools to call the existing Notion2API API."""

    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = (api_key or "").strip()
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def get(self, path: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}{path}", headers=self._headers())
        return _json_or_error(response)

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}{path}", headers=self._headers(), json=payload)
        return _json_or_error(response)


def _json_or_error(response: httpx.Response) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    try:
        data: Any = response.json() if "json" in content_type.lower() or response.content else {}
    except ValueError:
        data = {"text": response.text[:4000]}

    if response.status_code >= 400:
        return {
            "ok": False,
            "status_code": response.status_code,
            "error": data,
        }
    if isinstance(data, dict):
        data.setdefault("ok", True)
        data.setdefault("status_code", response.status_code)
        return data
    return {"ok": True, "status_code": response.status_code, "data": data}


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _model_info_from_entry(entry: Any) -> ModelInfo | None:
    if not isinstance(entry, dict):
        return None
    model_id = _string_or_none(entry.get("id"))
    if not model_id:
        return None
    return ModelInfo(
        id=model_id,
        object=_string_or_none(entry.get("object")),
        created=_int_or_none(entry.get("created")),
        owned_by=_string_or_none(entry.get("owned_by")),
    )


def _error_summary(data: dict[str, Any]) -> str | None:
    error = data.get("error") if isinstance(data, dict) else None
    if error is None:
        return None
    if isinstance(error, str):
        return error[:1000]
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()[:1000]
        try:
            return json.dumps(error, ensure_ascii=False)[:1000]
        except Exception:
            return str(error)[:1000]
    return str(error)[:1000]


def _extract_actual_model(data: dict[str, Any]) -> str:
    metadata = data.get("model_metadata") if isinstance(data.get("model_metadata"), dict) else {}
    actual = metadata.get("actual_model") if isinstance(metadata, dict) else None
    if isinstance(actual, str) and actual.strip():
        return actual.strip()
    direct = data.get("actual_model")
    return direct.strip() if isinstance(direct, str) and direct.strip() else ""


def _extract_chat_content(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts: list[str] = []
                for item in content:
                    if isinstance(item, dict):
                        text = item.get("text") or item.get("content")
                        if isinstance(text, str):
                            parts.append(text)
                return "\n".join(parts)
    return ""


def _extract_responses_text(data: dict[str, Any]) -> str:
    direct = data.get("output_text")
    if isinstance(direct, str):
        return direct
    output = data.get("output")
    if not isinstance(output, list):
        return ""
    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
    return "\n".join(parts)


def _local_conversation_db_path() -> Path:
    root = Path(__file__).resolve().parents[1]
    configured = os.getenv("DB_PATH", "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else root / path
    return root / "data" / "conversations.db"


def _runtime_audit(client: Notion2APIClient, requested_model: str) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    return {
        "requested_model": requested_model,
        "backend_base_url": client.base_url,
        "timeout_seconds": client.timeout,
        "session_state_path": str(DEFAULT_SESSION_STATE_PATH),
        "local_conversations_db": str(_local_conversation_db_path()),
        "imported_history_db": str(root / "data" / "chat_history.db"),
    }


def _now_ms() -> int:
    return int(time.time() * 1000)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    last_error: OSError | None = None
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                # Some network/sandbox filesystems do not support fsync. The
                # replace retry below is still the important Windows hardening.
                pass

        for attempt in range(CHAT_JOB_STATE_WRITE_RETRIES):
            try:
                os.replace(tmp, path)
                return
            except OSError as exc:
                last_error = exc
                if attempt >= CHAT_JOB_STATE_WRITE_RETRIES - 1:
                    break
                time.sleep(CHAT_JOB_STATE_WRITE_BACKOFF_SECONDS * (2 ** attempt))

        assert last_error is not None
        logger.warning(
            "Failed to atomically replace chat job state after retries",
            extra={
                "request_info": {
                    "event": "chat_job_state_replace_failed",
                    "path": str(path),
                    "tmp_path": str(tmp),
                    "error": f"{type(last_error).__name__}: {last_error}",
                }
            },
        )
        raise last_error
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _configured_chat_wait_seconds() -> float:
    raw = os.getenv("MCP_NOTION2API_CALL_WAIT_SECONDS", "")
    return _safe_float(raw, DEFAULT_CHAT_WAIT_SECONDS) if raw.strip() else DEFAULT_CHAT_WAIT_SECONDS


def _configured_chat_max_wait_seconds() -> float:
    raw = os.getenv("MCP_NOTION2API_MAX_CALL_WAIT_SECONDS", "")
    return _safe_float(raw, MAX_CHAT_WAIT_SECONDS) if raw.strip() else MAX_CHAT_WAIT_SECONDS


def _bounded_chat_wait_seconds(wait_seconds: float | None) -> float:
    requested = _configured_chat_wait_seconds() if wait_seconds is None else _safe_float(wait_seconds, DEFAULT_CHAT_WAIT_SECONDS)
    maximum = max(0.0, min(_configured_chat_max_wait_seconds(), 55.0))
    return max(0.0, min(requested, maximum))


def _normalize_request_id(request_id: str | None = None) -> str:
    raw = (request_id or "").strip()
    if not raw:
        return f"mcp-chat-{uuid.uuid4().hex}"
    normalized = re.sub(r"[^A-Za-z0-9_.:-]+", "-", raw).strip("-._:")
    return (normalized or f"mcp-chat-{uuid.uuid4().hex}")[:160]


def _session_key(session_name: str | None) -> str:
    raw = (session_name or DEFAULT_SESSION_NAME).strip().lower()
    key = re.sub(r"[^a-z0-9_.-]+", "-", raw).strip("-._")
    return key or DEFAULT_SESSION_NAME


def _valid_chat_job_state(data: Any) -> dict[str, Any] | None:
    if isinstance(data, dict) and isinstance(data.get("jobs"), dict):
        return data
    return None


def _load_chat_job_state_file(path: Path) -> dict[str, Any] | None:
    try:
        if not path.exists() or not path.is_file():
            return None
        return _valid_chat_job_state(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return None


def _job_timestamp(job: Any) -> int:
    if not isinstance(job, dict):
        return 0
    for key in ("updated_at", "created_at"):
        value = job.get(key)
        if isinstance(value, int):
            return value
    return 0


def _merge_chat_job_states(base: dict[str, Any], candidate: dict[str, Any]) -> bool:
    changed = False
    base_jobs = base.setdefault("jobs", {})
    candidate_jobs = candidate.get("jobs", {})
    if not isinstance(base_jobs, dict) or not isinstance(candidate_jobs, dict):
        return False
    for request_id, candidate_job in candidate_jobs.items():
        if not isinstance(candidate_job, dict):
            continue
        request_key = str(request_id)
        existing = base_jobs.get(request_key)
        if not isinstance(existing, dict) or _job_timestamp(candidate_job) > _job_timestamp(existing):
            base_jobs[request_key] = candidate_job
            changed = True
    return changed


def _recover_chat_job_state(path: Path) -> dict[str, Any]:
    state = _load_chat_job_state_file(path) or {"jobs": {}}
    tmp_paths = sorted(
        path.parent.glob(f"{path.name}.*.tmp"),
        key=lambda item: item.stat().st_mtime if item.exists() else 0,
    )
    recovered = False
    for tmp_path in tmp_paths:
        tmp_state = _load_chat_job_state_file(tmp_path)
        if tmp_state is None:
            continue
        recovered = _merge_chat_job_states(state, tmp_state) or recovered
    if recovered:
        try:
            _atomic_write_json(path, state)
        except OSError:
            logger.warning(
                "Recovered chat job state from temp files but could not promote canonical ledger",
                extra={
                    "request_info": {
                        "event": "chat_job_state_recovery_unpromoted",
                        "path": str(path),
                    }
                },
            )
    return state


def _load_chat_job_state(path: Path = DEFAULT_CHAT_JOB_STATE_PATH) -> dict[str, Any]:
    return _recover_chat_job_state(path)


def _save_chat_job_state(state: dict[str, Any], path: Path = DEFAULT_CHAT_JOB_STATE_PATH) -> None:
    if not isinstance(state.get("jobs"), dict):
        state["jobs"] = {}
    _atomic_write_json(path, state)


def _job_response_text(response: dict[str, Any] | None) -> str:
    if isinstance(response, dict):
        text = response.get("response_text")
        if isinstance(text, str):
            return text
    return ""


def _persist_chat_job(job: dict[str, Any]) -> None:
    with _CHAT_JOB_STATE_MUTEX:
        state = _load_chat_job_state()
        jobs = state.setdefault("jobs", {})
        jobs[str(job["request_id"])] = job
        _save_chat_job_state(state)


def _load_chat_job(request_id: str) -> dict[str, Any] | None:
    with _CHAT_JOB_STATE_MUTEX:
        state = _load_chat_job_state()
        job = state.get("jobs", {}).get(request_id)
        return job if isinstance(job, dict) else None


def _mark_chat_job_stale(job: dict[str, Any]) -> dict[str, Any]:
    updated = dict(job)
    updated["status"] = "stale"
    updated["updated_at"] = _now_ms()
    updated["error"] = "The MCP wrapper restarted or lost the in-memory task before this job completed. Check the local conversation by conversation_id before retrying."
    _persist_chat_job(updated)
    return updated


def _chat_output_from_backend(
    *,
    data: dict[str, Any],
    client: Notion2APIClient,
    model: str,
    session_key: str,
    conversation_id: str,
    session_created: bool,
    request_id: str,
    wait_seconds: float,
) -> dict[str, Any]:
    ok = bool(data.get("ok", False))
    status = "completed" if ok else "error"
    return {
        "ok": ok,
        "status_code": data.get("status_code"),
        "model": _extract_actual_model(data) or data.get("model") or model,
        "actual_model": _extract_actual_model(data),
        "model_metadata": data.get("model_metadata") if isinstance(data.get("model_metadata"), dict) else None,
        **_runtime_audit(client, model),
        "session_name": session_key,
        "conversation_id": conversation_id,
        "session_created": session_created,
        "status": status,
        "request_id": request_id,
        "job_id": request_id,
        "retry_safe": status != "completed",
        "wait_seconds": wait_seconds,
        "poll_hint": "" if status == "completed" else f"Retry with request_id={request_id} or call notion2api_get_chat_job.",
        "error": _error_summary(data),
        "response_text": _extract_chat_content(data),
        "raw": data,
    }


def _chat_pending_output(
    *,
    job: dict[str, Any],
    client: Notion2APIClient,
    model: str,
    session_key: str,
    conversation_id: str,
    session_created: bool,
    request_id: str,
    wait_seconds: float,
) -> dict[str, Any]:
    return {
        "ok": False,
        "status_code": None,
        "model": model,
        "actual_model": "",
        "model_metadata": None,
        **_runtime_audit(client, model),
        "session_name": session_key,
        "conversation_id": conversation_id,
        "session_created": session_created,
        "status": str(job.get("status") or "pending"),
        "request_id": request_id,
        "job_id": request_id,
        "retry_safe": True,
        "wait_seconds": wait_seconds,
        "poll_hint": f"Call notion2api_get_chat_job(request_id='{request_id}') or retry the same chat tool with the same request_id.",
        "error": job.get("error") if isinstance(job.get("error"), str) else None,
        "response_text": _job_response_text(job.get("response") if isinstance(job.get("response"), dict) else None),
        "raw": {"job": job, "job_state_path": str(DEFAULT_CHAT_JOB_STATE_PATH)},
    }


def _manifest_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _attachment_manifest_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_attachments = payload.get("attachments") if isinstance(payload, dict) else None
    if not isinstance(raw_attachments, list):
        return []
    manifest: list[dict[str, Any]] = []
    for item in raw_attachments:
        if not isinstance(item, dict):
            continue
        data_value = item.get("data") or item.get("file_data") or ""
        source = str(item.get("source") or "").strip()
        if not source and isinstance(data_value, str) and data_value.startswith("data:"):
            source = "inline_data"
        entry: dict[str, Any] = {
            "name": str(item.get("name") or item.get("filename") or item.get("file_name") or ""),
            "content_type": str(item.get("content_type") or item.get("mime_type") or ""),
            "source": source,
        }
        size = _manifest_int(item.get("size_bytes"))
        if size is not None:
            entry["size_bytes"] = size
        manifest.append({key: value for key, value in entry.items() if value != ""})
    return manifest


async def _run_chat_completion_job(
    *,
    client: Notion2APIClient,
    path: str,
    payload: dict[str, Any],
    model: str,
    session_key: str,
    conversation_id: str,
    session_created: bool,
    request_id: str,
    wait_seconds: float,
) -> dict[str, Any]:
    data = await client.post(path, payload)
    return _chat_output_from_backend(
        data=data,
        client=client,
        model=model,
        session_key=session_key,
        conversation_id=conversation_id,
        session_created=session_created,
        request_id=request_id,
        wait_seconds=wait_seconds,
    )


def _finalize_chat_job(request_id: str, task: asyncio.Task[dict[str, Any]]) -> None:
    try:
        response = task.result()
        status = str(response.get("status") or ("completed" if response.get("ok") else "error"))
        error = response.get("error") if isinstance(response.get("error"), str) else None
    except Exception as exc:
        response = None
        status = "error"
        error = f"{type(exc).__name__}: {exc}"
    with _CHAT_JOB_STATE_MUTEX:
        state = _load_chat_job_state()
        jobs = state.setdefault("jobs", {})
        job = jobs.get(request_id) if isinstance(jobs.get(request_id), dict) else {"request_id": request_id, "job_id": request_id}
        job = dict(job)
        job["status"] = status
        job["updated_at"] = _now_ms()
        if response is not None:
            job["response"] = response
            job["response_text"] = _job_response_text(response)
        if error:
            job["error"] = error
        jobs[request_id] = job
        _save_chat_job_state(state)
    _CHAT_JOB_TASKS.pop(request_id, None)


async def _submit_or_resume_chat_job(
    *,
    client: Notion2APIClient,
    path: str,
    payload: dict[str, Any],
    model: str,
    session_key: str,
    conversation_id: str,
    session_created: bool,
    request_id: str | None,
    wait_seconds: float | None,
) -> dict[str, Any]:
    normalized_id = _normalize_request_id(request_id)
    bounded_wait = _bounded_chat_wait_seconds(wait_seconds)
    metadata = payload.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        payload["metadata"] = metadata
    metadata.setdefault("mcp_request_id", normalized_id)
    attachment_manifest = _attachment_manifest_from_payload(payload)

    existing = _load_chat_job(normalized_id)
    task = _CHAT_JOB_TASKS.get(normalized_id)
    if existing:
        status = str(existing.get("status") or "")
        response = existing.get("response") if isinstance(existing.get("response"), dict) else None
        if response and status in {"completed", "error"}:
            return response
        if status == "running" and (task is None or task.done()):
            if task and task.done():
                _finalize_chat_job(normalized_id, task)
                refreshed = _load_chat_job(normalized_id)
                response = refreshed.get("response") if isinstance(refreshed, dict) and isinstance(refreshed.get("response"), dict) else None
                if response:
                    return response
                if refreshed:
                    existing = refreshed
            else:
                existing = _mark_chat_job_stale(existing)
                return _chat_pending_output(
                    job=existing,
                    client=client,
                    model=model,
                    session_key=session_key,
                    conversation_id=str(existing.get("conversation_id") or conversation_id),
                    session_created=False,
                    request_id=normalized_id,
                    wait_seconds=bounded_wait,
                )
        elif task is None and status in {"pending", "stale"}:
            return _chat_pending_output(
                job=existing,
                client=client,
                model=model,
                session_key=session_key,
                conversation_id=str(existing.get("conversation_id") or conversation_id),
                session_created=False,
                request_id=normalized_id,
                wait_seconds=bounded_wait,
            )

    if task is None:
        now = _now_ms()
        job = {
            "request_id": normalized_id,
            "job_id": normalized_id,
            "status": "running",
            "endpoint": path,
            "model": model,
            "session_name": session_key,
            "conversation_id": conversation_id,
            "session_created": session_created,
            "created_at": now,
            "updated_at": now,
            "wait_seconds": bounded_wait,
        }
        if attachment_manifest:
            job["attachment_manifest"] = attachment_manifest
        _persist_chat_job(job)
        task = asyncio.create_task(
            _run_chat_completion_job(
                client=client,
                path=path,
                payload=payload,
                model=model,
                session_key=session_key,
                conversation_id=conversation_id,
                session_created=session_created,
                request_id=normalized_id,
                wait_seconds=bounded_wait,
            )
        )
        _CHAT_JOB_TASKS[normalized_id] = task
        task.add_done_callback(lambda done_task, rid=normalized_id: _finalize_chat_job(rid, done_task))

    if bounded_wait > 0:
        done, _pending = await asyncio.wait({task}, timeout=bounded_wait)
        if done:
            result = task.result()
            _finalize_chat_job(normalized_id, task)
            return result

    current = _load_chat_job(normalized_id) or {
        "request_id": normalized_id,
        "job_id": normalized_id,
        "status": "running",
        "model": model,
        "session_name": session_key,
        "conversation_id": conversation_id,
    }
    if str(current.get("status") or "") == "running":
        current["status"] = "pending"
        current["updated_at"] = _now_ms()
        _persist_chat_job(current)
    return _chat_pending_output(
        job=current,
        client=client,
        model=model,
        session_key=session_key,
        conversation_id=conversation_id,
        session_created=session_created,
        request_id=normalized_id,
        wait_seconds=bounded_wait,
    )


def _chat_job_output(request_id: str, include_last_response: bool = False) -> ChatJobOutput:
    normalized_id = _normalize_request_id(request_id)
    task = _CHAT_JOB_TASKS.get(normalized_id)
    if task and task.done():
        _finalize_chat_job(normalized_id, task)
    job = _load_chat_job(normalized_id)
    if not job:
        return ChatJobOutput(ok=True, found=False, request_id=normalized_id, job_id=normalized_id)

    if str(job.get("status") or "") == "running" and normalized_id not in _CHAT_JOB_TASKS:
        job = _mark_chat_job_stale(job)

    response = job.get("response") if isinstance(job.get("response"), dict) else None
    last_response = None
    if include_last_response:
        last = _read_last_local_response(
            session_name=str(job.get("session_name") or DEFAULT_SESSION_NAME),
            conversation_id=str(job.get("conversation_id") or ""),
        )
        last_response = last.model_dump() if hasattr(last, "model_dump") else dict(last)

    return ChatJobOutput(
        ok=True,
        found=True,
        status=str(job.get("status") or ""),
        request_id=normalized_id,
        job_id=str(job.get("job_id") or normalized_id),
        session_name=str(job.get("session_name") or ""),
        conversation_id=str(job.get("conversation_id") or ""),
        model=str(job.get("model") or ""),
        endpoint=str(job.get("endpoint") or ""),
        created_at=int(job.get("created_at") or 0),
        updated_at=int(job.get("updated_at") or 0),
        response_text=str(job.get("response_text") or _job_response_text(response)),
        response=response,
        error=job.get("error") if isinstance(job.get("error"), str) else None,
        raw_job=job,
        last_response=last_response,
    )


def _load_session_state(path: Path = DEFAULT_SESSION_STATE_PATH) -> dict[str, str]:
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        sessions = data.get("sessions") if isinstance(data, dict) else None
        if isinstance(sessions, dict):
            return {str(k): str(v) for k, v in sessions.items() if str(v).strip()}
    except Exception:
        return {}
    return {}


def _save_session_state(sessions: dict[str, str], path: Path = DEFAULT_SESSION_STATE_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"sessions": sessions}, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        # Session continuity is helpful but should not break model calls.
        return


def _conversation_id_for_session(session_name: str | None = None, *, start_new_chat: bool = False) -> tuple[str, str, bool]:
    key = _session_key(session_name)
    sessions = _load_session_state()
    created = False
    if start_new_chat or not sessions.get(key):
        sessions[key] = f"mcp-{key}-{uuid.uuid4().hex}"
        _save_session_state(sessions)
        created = True
    return sessions[key], key, created


def _extract_conversation_id(data: dict[str, Any]) -> str:
    for key in ("conversation_id", "conversationId"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    headers = data.get("headers")
    if isinstance(headers, dict):
        for key in ("x-conversation-id", "X-Conversation-Id"):
            value = headers.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _resolve_session_conversation_id(session_name: str | None = None, conversation_id: str | None = None) -> tuple[str, str, str | None]:
    key = _session_key(session_name)
    explicit = (conversation_id or "").strip()
    if explicit:
        return key, explicit, None
    sessions = _load_session_state()
    resolved = sessions.get(key, "").strip()
    if not resolved:
        return key, "", f"No conversation id is bound to MCP session '{key}'."
    return key, resolved, None


def _read_local_messages(session_name: str | None = None, conversation_id: str | None = None, limit: int = 10) -> MessagesOutput:
    key, resolved_id, error = _resolve_session_conversation_id(session_name, conversation_id)
    db_path = _local_conversation_db_path()
    if error:
        return MessagesOutput(ok=False, session_name=key, conversation_id=resolved_id, db_path=str(db_path), error=error)
    if not db_path.exists():
        return MessagesOutput(ok=False, session_name=key, conversation_id=resolved_id, db_path=str(db_path), error="Local conversations database does not exist.")
    safe_limit = max(1, min(int(limit or 10), 100))
    try:
        with sqlite3.connect(str(db_path), timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            total_row = conn.execute("SELECT COUNT(1) AS cnt FROM messages WHERE conversation_id = ?", (resolved_id,)).fetchone()
            total = int(total_row["cnt"] or 0) if total_row else 0
            rows = conn.execute(
                """
                SELECT id, role, content, COALESCE(thinking, '') AS thinking, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (resolved_id, safe_limit),
            ).fetchall()
        messages = [
            {
                "id": int(row["id"]),
                "role": str(row["role"] or ""),
                "content": str(row["content"] or ""),
                "thinking": str(row["thinking"] or ""),
                "created_at": int(row["created_at"] or 0),
            }
            for row in rows
        ]
        messages.reverse()
        return MessagesOutput(ok=True, session_name=key, conversation_id=resolved_id, count=len(messages), total_count=total, db_path=str(db_path), messages=messages)
    except Exception as exc:
        return MessagesOutput(ok=False, session_name=key, conversation_id=resolved_id, db_path=str(db_path), error=f"{type(exc).__name__}: {exc}")


def _read_last_local_response(session_name: str | None = None, conversation_id: str | None = None) -> LastResponseOutput:
    key, resolved_id, error = _resolve_session_conversation_id(session_name, conversation_id)
    db_path = _local_conversation_db_path()
    if error:
        return LastResponseOutput(ok=False, session_name=key, conversation_id=resolved_id, db_path=str(db_path), error=error)
    if not db_path.exists():
        return LastResponseOutput(ok=False, session_name=key, conversation_id=resolved_id, db_path=str(db_path), error="Local conversations database does not exist.")
    try:
        with sqlite3.connect(str(db_path), timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT id, role, content, COALESCE(thinking, '') AS thinking, created_at
                FROM messages
                WHERE conversation_id = ? AND role = 'assistant'
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (resolved_id,),
            ).fetchone()
        if not row:
            return LastResponseOutput(ok=True, found=False, session_name=key, conversation_id=resolved_id, db_path=str(db_path))
        message = {
            "id": int(row["id"]),
            "role": str(row["role"] or ""),
            "content": str(row["content"] or ""),
            "thinking": str(row["thinking"] or ""),
            "created_at": int(row["created_at"] or 0),
        }
        return LastResponseOutput(ok=True, found=True, session_name=key, conversation_id=resolved_id, response_text=message["content"], message=message, db_path=str(db_path))
    except Exception as exc:
        return LastResponseOutput(ok=False, found=False, session_name=key, conversation_id=resolved_id, db_path=str(db_path), error=f"{type(exc).__name__}: {exc}")


PROMPT_PACK_DIR = Path(
    os.getenv(
        "MCP_NOTION2API_PROMPT_DIR",
        str(Path(__file__).resolve().parents[1] / "prompts" / "notion2api-mcp"),
    )
)
PROMPT_INDEX_PATH = Path(os.getenv("MCP_NOTION2API_PROMPT_INDEX", str(PROMPT_PACK_DIR / "index.json")))


def _load_prompt_index() -> dict[str, Any]:
    try:
        data = json.loads(PROMPT_INDEX_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"prompts": []}
    except Exception:
        return {"prompts": []}


def _prompt_metadata(name: str) -> dict[str, Any]:
    prompts = _load_prompt_index().get("prompts", [])
    if isinstance(prompts, list):
        for item in prompts:
            if isinstance(item, dict) and item.get("name") == name:
                return item
    return {"name": name, "title": name, "description": "Notion2API MCP prompt.", "file": ""}


def _load_prompt_body(file_name: str) -> str:
    safe_name = Path(str(file_name or "")).name
    if not safe_name:
        return "Prompt body is unavailable: no file was configured for this prompt."
    path = PROMPT_PACK_DIR / safe_name
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"Prompt body is unavailable: {type(exc).__name__}: {exc}"


def _format_prompt_arguments(arguments: dict[str, Any]) -> str:
    clean = {key: value for key, value in arguments.items() if value not in (None, "")}
    if not clean:
        return ""
    lines = ["", "## Invocation arguments"]
    for key, value in clean.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def _prompt_messages(name: str, arguments: dict[str, Any] | None = None) -> list[dict[str, str]]:
    meta = _prompt_metadata(name)
    body = _load_prompt_body(str(meta.get("file") or ""))
    rendered = body + _format_prompt_arguments(arguments or {})
    return [{"role": "user", "content": rendered}]


def register_notion2api_prompts(server: FastMCP) -> None:
    """Register prompt-pack entries with FastMCP so clients expose prompts/list and prompts/get."""

    meta = _prompt_metadata("notion2api_operator")

    @server.prompt(name="notion2api_operator", title=meta.get("title"), description=meta.get("description"))
    def notion2api_operator() -> list[dict[str, str]]:
        return _prompt_messages("notion2api_operator")

    meta = _prompt_metadata("notion2api_tool_router")

    @server.prompt(name="notion2api_tool_router", title=meta.get("title"), description=meta.get("description"))
    def notion2api_tool_router(user_request: str) -> list[dict[str, str]]:
        return _prompt_messages("notion2api_tool_router", {"user_request": user_request})

    meta = _prompt_metadata("notion2api_output_schema_writer")

    @server.prompt(name="notion2api_output_schema_writer", title=meta.get("title"), description=meta.get("description"))
    def notion2api_output_schema_writer(operation_name: str, current_schema: str = "") -> list[dict[str, str]]:
        return _prompt_messages(
            "notion2api_output_schema_writer",
            {"operation_name": operation_name, "current_schema": current_schema},
        )

    meta = _prompt_metadata("notion2api_provider_debugger")

    @server.prompt(name="notion2api_provider_debugger", title=meta.get("title"), description=meta.get("description"))
    def notion2api_provider_debugger(error_log: str = "", operation: str = "") -> list[dict[str, str]]:
        return _prompt_messages(
            "notion2api_provider_debugger",
            {"error_log": error_log, "operation": operation},
        )

    meta = _prompt_metadata("notion2api_content_sync")

    @server.prompt(name="notion2api_content_sync", title=meta.get("title"), description=meta.get("description"))
    def notion2api_content_sync(content: str, target: str = "") -> list[dict[str, str]]:
        return _prompt_messages("notion2api_content_sync", {"content": content, "target": target})

    meta = _prompt_metadata("notion2api_regression_validation")

    @server.prompt(name="notion2api_regression_validation", title=meta.get("title"), description=meta.get("description"))
    def notion2api_regression_validation(change_summary: str) -> list[dict[str, str]]:
        return _prompt_messages("notion2api_regression_validation", {"change_summary": change_summary})

    meta = _prompt_metadata("notion2api_security_redaction")

    @server.prompt(name="notion2api_security_redaction", title=meta.get("title"), description=meta.get("description"))
    def notion2api_security_redaction(raw_text: str) -> list[dict[str, str]]:
        return _prompt_messages("notion2api_security_redaction", {"raw_text": raw_text})


def create_server(
    *,
    base_url: str,
    api_key: str | None,
    timeout: float,
    host: str,
    port: int,
    mcp_path: str,
    stateless_http: bool = True,
) -> FastMCP:
    client = Notion2APIClient(base_url=base_url, api_key=api_key, timeout=timeout)
    transport_security = _transport_security_settings(host=host)
    server = FastMCP(
        name="notion2api",
        instructions=(
            "Use these tools to call the user's private local Notion2API service. "
            "Start with notion2api_health or notion2api_list_models if service status or model IDs are uncertain. "
            "Do not claim Notion2API completed a model response unless a tool result includes ok=true and response_text/content."
        ),
        host=host,
        port=port,
        streamable_http_path=mcp_path,
        stateless_http=stateless_http,
        json_response=True,
        transport_security=transport_security,
    )
    register_notion2api_prompts(server)

    @server.tool(description="Check whether the configured Notion2API backend is reachable and healthy.", structured_output=True)
    async def notion2api_health() -> HealthOutput:
        data = await client.get("/health")
        return HealthOutput(
            ok=bool(data.get("ok", False)),
            status_code=data.get("status_code"),
            status=data.get("status"),
            accounts=data.get("accounts"),
            accounts_total=data.get("accounts_total"),
            accounts_cooling=data.get("accounts_cooling"),
            uptime=data.get("uptime"),
            raw=data,
        )

    @server.tool(description="List Notion2API models from the configured backend.", structured_output=True)
    async def notion2api_list_models() -> ListModelsOutput:
        data = await client.get("/v1/models")
        raw_models = data.get("data") if isinstance(data, dict) else None
        model_list = []
        if isinstance(raw_models, list):
            for entry in raw_models:
                info = _model_info_from_entry(entry)
                if info is not None:
                    model_list.append(info)
        return ListModelsOutput(
            ok=bool(data.get("ok", False)),
            status_code=data.get("status_code"),
            count=len(model_list),
            models=model_list,
            error=_error_summary(data),
        )

    @server.tool(description="Send a single prompt to Notion2API through /v1/chat/completions and return the assistant text. Uses a persistent MCP session unless start_new_chat=true.", structured_output=True)
    async def notion2api_chat(
        prompt: str,
        model: str = DEFAULT_MODEL,
        system_prompt: str | None = None,
        persist_remote_chat: bool = True,
        session_name: str = DEFAULT_SESSION_NAME,
        start_new_chat: bool = False,
        request_id: str | None = None,
        wait_seconds: float | None = None,
        attachments: FileAttachments = None,
    ) -> ChatOutput:
        conversation_id, session_key, session_created = _conversation_id_for_session(
            session_name,
            start_new_chat=start_new_chat,
        )
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        prepared = prepare_mcp_file_attachments(attachments)
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "conversation_id": conversation_id,
            "metadata": {
                "persist_remote_chat": persist_remote_chat,
                "mcp_session_name": session_key,
            },
        }
        if prepared:
            payload["attachments"] = prepared
        return await _submit_or_resume_chat_job(
            client=client,
            path="/v1/chat/completions",
            payload=payload,
            model=model,
            session_key=session_key,
            conversation_id=conversation_id,
            session_created=session_created,
            request_id=request_id,
            wait_seconds=wait_seconds,
        )

    @server.tool(description="Call Notion2API /v1/chat/completions with an explicit OpenAI-style messages array. Uses a persistent MCP session unless start_new_chat=true.", structured_output=True)
    async def notion2api_chat_completion(
        messages: list[dict[str, Any]],
        model: str = DEFAULT_MODEL,
        persist_remote_chat: bool = True,
        session_name: str = DEFAULT_SESSION_NAME,
        start_new_chat: bool = False,
        request_id: str | None = None,
        wait_seconds: float | None = None,
        attachments: FileAttachments = None,
    ) -> ChatOutput:
        conversation_id, session_key, session_created = _conversation_id_for_session(
            session_name,
            start_new_chat=start_new_chat,
        )
        prepared = prepare_mcp_file_attachments(attachments)
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "conversation_id": conversation_id,
            "metadata": {
                "persist_remote_chat": persist_remote_chat,
                "mcp_session_name": session_key,
            },
        }
        if prepared:
            payload["attachments"] = prepared
        return await _submit_or_resume_chat_job(
            client=client,
            path="/v1/chat/completions",
            payload=payload,
            model=model,
            session_key=session_key,
            conversation_id=conversation_id,
            session_created=session_created,
            request_id=request_id,
            wait_seconds=wait_seconds,
        )

    @server.tool(description="Call Notion2API /v1/responses and return extracted output text plus the raw response.", structured_output=True)
    async def notion2api_responses(
        input_text: str,
        model: str = DEFAULT_MODEL,
        instructions: str | None = None,
        persist_remote_chat: bool = True,
        attachments: FileAttachments = None,
    ) -> ResponsesOutput:
        prepared = prepare_mcp_file_attachments(attachments)
        payload: dict[str, Any] = {
            "model": model,
            "input": input_text,
            "metadata": {"persist_remote_chat": persist_remote_chat},
        }
        if instructions:
            payload["instructions"] = instructions
        if prepared:
            payload["attachments"] = prepared
        data = await client.post("/v1/responses", payload)
        return {
            "ok": data.get("ok", False),
            "status_code": data.get("status_code"),
            "model": _extract_actual_model(data) or data.get("model") or model,
            "actual_model": _extract_actual_model(data),
            "model_metadata": data.get("model_metadata") if isinstance(data.get("model_metadata"), dict) else None,
            **_runtime_audit(client, model),
            "response_text": _extract_responses_text(data),
            "raw": data,
        }

    @server.tool(description="List named persistent Notion2API MCP chat sessions.", structured_output=True)
    async def notion2api_list_sessions() -> ListSessionsOutput:
        sessions = _load_session_state()
        items = [
            {"session_name": name, "conversation_id": conversation_id}
            for name, conversation_id in sorted(sessions.items())
        ]
        return ListSessionsOutput(
            ok=True,
            count=len(items),
            default_session=DEFAULT_SESSION_NAME,
            state_path=str(DEFAULT_SESSION_STATE_PATH),
            sessions=items,
        )

    @server.tool(description="Read recent locally persisted messages for a persistent Notion2API MCP session without sending a new chat message. Useful after a client-side timeout.", structured_output=True)
    async def notion2api_get_messages(
        session_name: str = DEFAULT_SESSION_NAME,
        limit: int = 10,
        conversation_id: str | None = None,
    ) -> MessagesOutput:
        return _read_local_messages(session_name=session_name, conversation_id=conversation_id, limit=limit)

    @server.tool(description="Read the latest locally persisted assistant response for a persistent Notion2API MCP session without sending a new chat message. Useful after a client-side timeout.", structured_output=True)
    async def notion2api_get_last_response(
        session_name: str = DEFAULT_SESSION_NAME,
        conversation_id: str | None = None,
    ) -> LastResponseOutput:
        return _read_last_local_response(session_name=session_name, conversation_id=conversation_id)

    @server.tool(description="Inspect a retry-safe Notion2API MCP chat job by request_id. Use this after notion2api_chat returns status=pending or after a connector timeout.", structured_output=True)
    async def notion2api_get_chat_job(
        request_id: str,
        include_last_response: bool = False,
    ) -> ChatJobOutput:
        return _chat_job_output(request_id=request_id, include_last_response=include_last_response)

    @server.tool(description="Start a fresh persistent Notion2API MCP chat for a named session.", structured_output=True)
    async def notion2api_reset_session(session_name: str = DEFAULT_SESSION_NAME) -> SessionActionOutput:
        key = _session_key(session_name)
        sessions = _load_session_state()
        previous = sessions.get(key)
        conversation_id, session_key, _created = _conversation_id_for_session(key, start_new_chat=True)
        return SessionActionOutput(
            ok=True,
            action="reset",
            session_name=session_key,
            conversation_id=conversation_id,
            previous_conversation_id=previous,
            state_path=str(DEFAULT_SESSION_STATE_PATH),
        )

    @server.tool(description="Rename a persistent Notion2API MCP chat session without changing its conversation binding.", structured_output=True)
    async def notion2api_rename_session(
        old_session_name: str,
        new_session_name: str,
        overwrite: bool = False,
    ) -> SessionActionOutput:
        old_key = _session_key(old_session_name)
        new_key = _session_key(new_session_name)
        sessions = _load_session_state()
        if old_key not in sessions:
            return SessionActionOutput(
                ok=False,
                action="rename",
                session_name=new_key,
                conversation_id="",
                previous_session_name=old_key,
                state_path=str(DEFAULT_SESSION_STATE_PATH),
            )
        if new_key in sessions and not overwrite and new_key != old_key:
            return SessionActionOutput(
                ok=False,
                action="rename",
                session_name=new_key,
                conversation_id=sessions[new_key],
                previous_session_name=old_key,
                previous_conversation_id=sessions[old_key],
                overwritten=False,
                state_path=str(DEFAULT_SESSION_STATE_PATH),
            )
        conversation_id = sessions[old_key]
        previous_target = sessions.get(new_key)
        if old_key != new_key:
            sessions[new_key] = conversation_id
            sessions.pop(old_key, None)
            _save_session_state(sessions)
        return SessionActionOutput(
            ok=True,
            action="rename",
            session_name=new_key,
            conversation_id=conversation_id,
            previous_session_name=old_key,
            previous_conversation_id=previous_target,
            overwritten=bool(previous_target and previous_target != conversation_id),
            state_path=str(DEFAULT_SESSION_STATE_PATH),
        )

    return server


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_csv(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name, "")
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return values or default


def _transport_security_settings(host: str) -> TransportSecuritySettings:
    default_hosts = [
        "127.0.0.1:*",
        "localhost:*",
        "[::1]:*",
        "0.0.0.0:*",
        "notion2api-mcp.ptelectronics.net",
        "notion2api-mcp.ptelectronics.net:*",
    ]
    if host and host not in {"0.0.0.0", "::"}:
        default_hosts.append(host if ":" in host else f"{host}:*")

    default_origins = [
        "http://127.0.0.1:*",
        "http://localhost:*",
        "http://[::1]:*",
        "https://notion2api-mcp.ptelectronics.net",
        "http://notion2api-mcp.ptelectronics.net",
        "https://chatgpt.com",
        "https://chat.openai.com",
    ]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=_env_bool("MCP_ENABLE_DNS_REBINDING_PROTECTION", True),
        allowed_hosts=_env_csv("MCP_ALLOWED_HOSTS", default_hosts),
        allowed_origins=_env_csv("MCP_ALLOWED_ORIGINS", default_origins),
    )


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Notion2API MCP wrapper.")
    parser.add_argument("--transport", choices=("streamable-http", "stdio", "sse"), default=os.getenv("MCP_TRANSPORT", "streamable-http"))
    parser.add_argument("--base-url", default=os.getenv("MCP_NOTION2API_BASE_URL", os.getenv("NOTION2API_BASE_URL", DEFAULT_BASE_URL)))
    parser.add_argument(
        "--api-key",
        default=os.getenv(
            "MCP_NOTION2API_API_KEY",
            os.getenv("NOTION2API_API_KEY", os.getenv("NOTION2API_KEY", os.getenv("API_KEY", ""))),
        ),
    )
    parser.add_argument("--timeout", type=float, default=_env_float("MCP_NOTION2API_TIMEOUT", DEFAULT_TIMEOUT_SECONDS))
    parser.add_argument("--host", default=os.getenv("MCP_HOST", DEFAULT_MCP_HOST))
    parser.add_argument("--port", type=int, default=_env_int("MCP_PORT", DEFAULT_MCP_PORT))
    parser.add_argument("--mcp-path", default=os.getenv("MCP_PATH", DEFAULT_MCP_PATH))
    args = parser.parse_args(argv)

    server = create_server(
        base_url=args.base_url,
        api_key=args.api_key,
        timeout=args.timeout,
        host=args.host,
        port=args.port,
        mcp_path=args.mcp_path,
    )
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
