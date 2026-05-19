from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse


def openai_error_payload(
    message: str,
    code: str,
    status_code: int = 400,
    error_type: str = "invalid_request_error",
    param: str | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "message": message,
            "type": error_type,
            "param": param,
            "code": code,
        }
    }


def openai_error(
    message: str,
    code: str,
    status_code: int = 400,
    error_type: str = "invalid_request_error",
    param: str | None = None,
) -> None:
    raise HTTPException(
        status_code=status_code,
        detail=openai_error_payload(
            message=message,
            code=code,
            status_code=status_code,
            error_type=error_type,
            param=param,
        ),
    )


def openai_error_response(
    message: str,
    code: str,
    status_code: int = 400,
    error_type: str = "invalid_request_error",
    param: str | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=openai_error_payload(
            message=message,
            code=code,
            status_code=status_code,
            error_type=error_type,
            param=param,
        ),
    )
