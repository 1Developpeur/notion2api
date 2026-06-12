import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from app.config import is_lite_mode, is_standard_mode

# Disable rate limiting when DISABLE_RATE_LIMIT=True.
_disable_flag = os.getenv("DISABLE_RATE_LIMIT", "").strip().lower()
_rate_limit_disabled = _disable_flag == "true"

# Set rate limits dynamically by APP_MODE.
# Lite mode: 30/minute.
# Standard mode: 25/minute with thinking and search support.
# Heavy mode: 20/minute.
if is_lite_mode():
    default_limit = "30/minute"
elif is_standard_mode():
    default_limit = "25/minute"
else:
    default_limit = "20/minute"

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[] if _rate_limit_disabled else [default_limit],
    enabled=not _rate_limit_disabled,
)
