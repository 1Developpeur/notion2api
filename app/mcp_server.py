from __future__ import annotations

import argparse
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Literal

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

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_MCP_HOST = "127.0.0.1"
DEFAULT_MCP_PORT = 8130
DEFAULT_MCP_PATH = "/mcp"
DEFAULT_TIMEOUT_SECONDS = 180.0
DEFAULT_MODEL = "claude-opus4.8"
DEFAULT_SESSION_NAME = "op"
DEFAULT_SESSION_STATE_PATH = Path(
    os.getenv(
        "MCP_NOTION2API_SESSION_STATE",
        str(Path.cwd() / ".notion2api_mcp_sessions.json"),
    )
)


class HealthOutput(BaseModel):
    ok: bool = Field(description="Whether the backend health call succeeded.")
    status_code: int | None = Field(default=None, description="HTTP status code returned by Notion2API.")
    status: str | None = Field(default=None, description="Backend status string, usually ok.")
    accounts: int | None = Field(default=None, description="Ready account count reported by Notion2API.")
    accounts_total: int | None = Field(default=None, description="Total configured account count.")
    accounts_cooling: int | None = Field(default=None, description="Number of accounts currently cooling down.")
    uptime: int | float | None = Field(default=None, description="Backend uptime, if reported.")
    raw: dict[str, Any] = Field(default_factory=dict, description="Raw backend health response.")


class ListModelsOutput(BaseModel):
    ok: bool = Field(description="Whether the models call succeeded.")
    status_code: int | None = Field(default=None, description="HTTP status code returned by Notion2API.")
    count: int = Field(default=0, description="Number of model entries returned.")
    models: list[dict[str, Any]] = Field(default_factory=list, description="Raw OpenAI-style model entries.")
    raw: dict[str, Any] = Field(default_factory=dict, description="Raw backend model response.")


class ChatOutput(BaseModel):
    ok: bool = Field(description="Whether the model call succeeded.")
    status_code: int | None = Field(default=None, description="HTTP status code returned by Notion2API.")
    model: str = Field(description="Requested model id passed through the MCP wrapper.")
    actual_model: str = Field(default="", description="Actual Notion model/provider route used, if returned.")
    model_metadata: dict[str, Any] | None = Field(default=None, description="Notion2API model metadata, if any.")
    session_name: str | None = Field(default=None, description="Normalized MCP session name.")
    conversation_id: str | None = Field(default=None, description="Stable Notion2API conversation id used for the request.")
    session_created: bool | None = Field(default=None, description="True when the wrapper created a new MCP conversation binding.")
    response_text: str = Field(default="", description="Extracted assistant response text.")
    raw: dict[str, Any] = Field(default_factory=dict, description="Raw backend response.")


class ResponsesOutput(BaseModel):
    ok: bool = Field(description="Whether the responses endpoint call succeeded.")
    status_code: int | None = Field(default=None, description="HTTP status code returned by Notion2API.")
    model: str = Field(description="Requested model id passed through the MCP wrapper.")
    actual_model: str = Field(default="", description="Actual Notion model/provider route used, if returned.")
    model_metadata: dict[str, Any] | None = Field(default=None, description="Notion2API model metadata, if any.")
    response_text: str = Field(default="", description="Extracted response output text.")
    raw: dict[str, Any] = Field(default_factory=dict, description="Raw backend response.")


class SessionInfo(BaseModel):
    session_name: str = Field(description="Normalized MCP session name.")
    conversation_id: str = Field(description="Stable conversation id bound to this MCP session.")


class ListSessionsOutput(BaseModel):
    ok: bool = Field(default=True, description="Whether the session listing succeeded.")
    count: int = Field(description="Number of known MCP sessions.")
    default_session: str = Field(description="Default session name used by OP calls.")
    state_path: str = Field(description="Path to the MCP session state file.")
    sessions: list[SessionInfo] = Field(default_factory=list, description="Known named MCP session bindings.")


class SessionActionOutput(BaseModel):
    ok: bool = Field(description="Whether the session operation succeeded.")
    action: str = Field(description="Operation performed: reset or rename.")
    session_name: str = Field(description="Normalized target session name.")
    conversation_id: str = Field(description="Conversation id now bound to the target session.")
    previous_session_name: str | None = Field(default=None, description="Previous session name for rename operations.")
    previous_conversation_id: str | None = Field(default=None, description="Prior conversation id replaced or renamed, if any.")
    overwritten: bool = Field(default=False, description="Whether an existing target session was overwritten.")
    state_path: str = Field(description="Path to the MCP session state file.")


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


def _session_key(session_name: str | None) -> str:
    raw = (session_name or DEFAULT_SESSION_NAME).strip().lower()
    key = re.sub(r"[^a-z0-9_.-]+", "-", raw).strip("-._")
    return key or DEFAULT_SESSION_NAME


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
        models = data.get("data") if isinstance(data, dict) else None
        model_list = models if isinstance(models, list) else []
        return ListModelsOutput(
            ok=bool(data.get("ok", False)),
            status_code=data.get("status_code"),
            count=len(model_list),
            models=model_list,
            raw=data,
        )

    @server.tool(description="Send a single prompt to Notion2API through /v1/chat/completions and return the assistant text. Uses a persistent MCP session unless start_new_chat=true.", structured_output=True)
    async def notion2api_chat(
        prompt: str,
        model: str = DEFAULT_MODEL,
        system_prompt: str | None = None,
        persist_remote_chat: bool = True,
        session_name: str = DEFAULT_SESSION_NAME,
        start_new_chat: bool = False,
    ) -> ChatOutput:
        conversation_id, session_key, session_created = _conversation_id_for_session(
            session_name,
            start_new_chat=start_new_chat,
        )
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
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
        data = await client.post("/v1/chat/completions", payload)
        return {
            "ok": data.get("ok", False),
            "status_code": data.get("status_code"),
            "model": model,
            "actual_model": _extract_actual_model(data),
            "model_metadata": data.get("model_metadata") if isinstance(data.get("model_metadata"), dict) else None,
            "session_name": session_key,
            "conversation_id": conversation_id,
            "session_created": session_created,
            "response_text": _extract_chat_content(data),
            "raw": data,
        }

    @server.tool(description="Call Notion2API /v1/chat/completions with an explicit OpenAI-style messages array. Uses a persistent MCP session unless start_new_chat=true.", structured_output=True)
    async def notion2api_chat_completion(
        messages: list[dict[str, Any]],
        model: str = DEFAULT_MODEL,
        persist_remote_chat: bool = True,
        session_name: str = DEFAULT_SESSION_NAME,
        start_new_chat: bool = False,
    ) -> ChatOutput:
        conversation_id, session_key, session_created = _conversation_id_for_session(
            session_name,
            start_new_chat=start_new_chat,
        )
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
        data = await client.post("/v1/chat/completions", payload)
        return {
            "ok": data.get("ok", False),
            "status_code": data.get("status_code"),
            "model": model,
            "actual_model": _extract_actual_model(data),
            "model_metadata": data.get("model_metadata") if isinstance(data.get("model_metadata"), dict) else None,
            "session_name": session_key,
            "conversation_id": conversation_id,
            "session_created": session_created,
            "response_text": _extract_chat_content(data),
            "raw": data,
        }

    @server.tool(description="Call Notion2API /v1/responses and return extracted output text plus the raw response.", structured_output=True)
    async def notion2api_responses(
        input_text: str,
        model: str = DEFAULT_MODEL,
        instructions: str | None = None,
        persist_remote_chat: bool = True,
    ) -> ResponsesOutput:
        payload: dict[str, Any] = {
            "model": model,
            "input": input_text,
            "metadata": {"persist_remote_chat": persist_remote_chat},
        }
        if instructions:
            payload["instructions"] = instructions
        data = await client.post("/v1/responses", payload)
        return {
            "ok": data.get("ok", False),
            "status_code": data.get("status_code"),
            "model": model,
            "actual_model": _extract_actual_model(data),
            "model_metadata": data.get("model_metadata") if isinstance(data.get("model_metadata"), dict) else None,
            "response_text": _extract_responses_text(data),
            "raw": data,
        }

    @server.tool(description="List named persistent Notion2API MCP chat sessions.", structured_output=True)
    async def notion2api_list_sessions() -> ListSessionsOutput:
        sessions = _load_session_state()
        items = [
            SessionInfo(session_name=name, conversation_id=conversation_id)
            for name, conversation_id in sorted(sessions.items())
        ]
        return ListSessionsOutput(
            count=len(items),
            default_session=DEFAULT_SESSION_NAME,
            state_path=str(DEFAULT_SESSION_STATE_PATH),
            sessions=items,
        )

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

