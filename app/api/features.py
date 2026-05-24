from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.attachments.runtime_config import (
    attachment_runtime_state,
    set_runtime_attachment_enabled,
)
from app.attachments.security import AttachmentPolicy
from app.config import API_KEY, HOST, ALLOWED_ORIGINS

router = APIRouter(prefix="/features", tags=["features"])


def _is_public_host() -> bool:
    host = str(HOST or "").strip().lower()
    return host in {"0.0.0.0", "::", "[::]"}


def _attachment_warnings(policy: AttachmentPolicy) -> list[str]:
    warnings: list[str] = []
    if not policy.enabled:
        warnings.append("File uploads are disabled. Enable them in Settings or set ENABLE_ATTACHMENTS=true.")
    if policy.enabled and _is_public_host() and not API_KEY:
        warnings.append("File uploads are enabled while HOST allows network access and API_KEY is empty. Set API_KEY or bind to 127.0.0.1.")
    if policy.enabled and policy.allow_remote_urls and not API_KEY:
        warnings.append("Remote URL attachments are enabled without API_KEY. This is not recommended.")
    if policy.enabled and policy.allow_local_paths:
        warnings.append("Local path attachments are enabled. Restrict ATTACHMENT_LOCAL_ROOT and keep this server local-only.")
    return warnings


def _attachment_payload(policy: AttachmentPolicy) -> dict[str, object]:
    return {
        "enabled": policy.enabled,
        "max_attachments_per_request": policy.max_attachments_per_request,
        "max_attachment_bytes": policy.max_attachment_bytes,
        "allowed_mime_types": sorted(policy.allowed_mime_types),
        "remote_urls_enabled": policy.allow_remote_urls,
        "local_paths_enabled": policy.allow_local_paths,
        "non_default_remote_ports_enabled": policy.allow_non_default_remote_ports,
        "local_root_configured": bool(policy.local_root),
        "warnings": _attachment_warnings(policy),
        "runtime": attachment_runtime_state(),
    }


def _features_payload() -> dict[str, object]:
    policy = AttachmentPolicy.from_env()
    return {
        "attachments": _attachment_payload(policy),
        "server": {
            "host": HOST,
            "api_key_required": bool(API_KEY),
            "allowed_origins": ALLOWED_ORIGINS,
        },
    }


@router.get("")
def get_features() -> dict[str, object]:
    return _features_payload()


@router.post("/attachments")
async def set_attachment_feature(request: Request) -> dict[str, object]:
    body: dict[str, Any]
    try:
        parsed = await request.json()
    except Exception:
        parsed = {}
    body = parsed if isinstance(parsed, dict) else {}
    enabled = bool(body.get("enabled"))
    set_runtime_attachment_enabled(enabled)
    return _features_payload()
