from __future__ import annotations

import argparse
import os
from typing import Any, Literal

import httpx
from mcp.server.fastmcp import FastMCP

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
DEFAULT_MODEL = "claude-sonnet4.6"


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
    )

    @server.tool(description="Check whether the configured Notion2API backend is reachable and healthy.")
    async def notion2api_health() -> dict[str, Any]:
        return await client.get("/health")

    @server.tool(description="List Notion2API models from the configured backend.")
    async def notion2api_list_models() -> dict[str, Any]:
        data = await client.get("/v1/models")
        models = data.get("data") if isinstance(data, dict) else None
        if isinstance(models, list):
            return {
                "ok": data.get("ok", True),
                "status_code": data.get("status_code"),
                "count": len(models),
                "models": models,
            }
        return data

    @server.tool(description="Send a single prompt to Notion2API through /v1/chat/completions and return the assistant text.")
    async def notion2api_chat(
        prompt: str,
        model: str = DEFAULT_MODEL,
        system_prompt: str | None = None,
        persist_remote_chat: bool = True,
    ) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "metadata": {"persist_remote_chat": persist_remote_chat},
        }
        data = await client.post("/v1/chat/completions", payload)
        return {
            "ok": data.get("ok", False),
            "status_code": data.get("status_code"),
            "model": model,
            "response_text": _extract_chat_content(data),
            "raw": data,
        }

    @server.tool(description="Call Notion2API /v1/chat/completions with an explicit OpenAI-style messages array.")
    async def notion2api_chat_completion(
        messages: list[dict[str, Any]],
        model: str = DEFAULT_MODEL,
        persist_remote_chat: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "metadata": {"persist_remote_chat": persist_remote_chat},
        }
        data = await client.post("/v1/chat/completions", payload)
        return {
            "ok": data.get("ok", False),
            "status_code": data.get("status_code"),
            "model": model,
            "response_text": _extract_chat_content(data),
            "raw": data,
        }

    @server.tool(description="Call Notion2API /v1/responses and return extracted output text plus the raw response.")
    async def notion2api_responses(
        input_text: str,
        model: str = DEFAULT_MODEL,
        instructions: str | None = None,
        persist_remote_chat: bool = True,
    ) -> dict[str, Any]:
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
            "response_text": _extract_responses_text(data),
            "raw": data,
        }

    return server


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
    parser.add_argument("--api-key", default=os.getenv("MCP_NOTION2API_API_KEY", os.getenv("NOTION2API_API_KEY", os.getenv("API_KEY", ""))))
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

