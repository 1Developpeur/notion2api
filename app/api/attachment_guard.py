from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.attachments.security import AttachmentPolicy
from app.config import API_KEY, HOST
from app.core.errors import openai_error_payload


def _is_public_host() -> bool:
    host = str(HOST or "").strip().lower()
    return host in {"0.0.0.0", "::", "[::]"}


def _looks_like_attachment_request(request: Request) -> bool:
    path = request.url.path
    if path not in {"/v1/chat/completions", "/v1/responses"}:
        return False
    content_type = request.headers.get("content-type", "").lower()
    return "application/json" in content_type or "multipart/form-data" in content_type


def _blocked_attachment_configuration(policy: AttachmentPolicy) -> str:
    if not policy.enabled:
        return ""
    if _is_public_host() and not API_KEY:
        return "Attachments are enabled while HOST allows network access and API_KEY is empty. Set API_KEY or bind HOST to 127.0.0.1."
    if policy.allow_remote_urls and not API_KEY:
        return "Remote URL attachments require API_KEY to be set."
    if policy.allow_local_paths and not policy.local_root:
        return "Local path attachments require ATTACHMENT_LOCAL_ROOT to be configured."
    return ""


async def attachment_deployment_guard(request: Request, call_next: Callable[[Request], Any]) -> Any:
    """Block unsafe attachment deployments before request bodies are processed."""
    if _looks_like_attachment_request(request):
        policy = AttachmentPolicy.from_env()
        reason = _blocked_attachment_configuration(policy)
        if reason:
            return JSONResponse(
                status_code=403,
                content=openai_error_payload(
                    message=reason,
                    code="unsafe_attachment_configuration",
                    status_code=403,
                    error_type="configuration_error",
                    param="attachments",
                ),
            )
    return await call_next(request)
