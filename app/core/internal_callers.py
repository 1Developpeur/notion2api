from __future__ import annotations

import ipaddress

from fastapi import Request

REPO_AI_CALLER_HEADER = "x-repo-ai-internal"
REPO_AI_CALLER_VALUE = "1"


def _is_loopback_host(value: str) -> bool:
    host = str(value or "").strip().lower().strip("[]")
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_repo_ai_internal_request(request: Request) -> bool:
    client_host = request.client.host if request.client else ""
    request_host = request.url.hostname or ""
    marker = request.headers.get(REPO_AI_CALLER_HEADER, "")
    return (
        marker == REPO_AI_CALLER_VALUE
        and _is_loopback_host(client_host)
        and _is_loopback_host(request_host)
    )
