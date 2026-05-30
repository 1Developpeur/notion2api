import logging
import json
from datetime import datetime


class JsonFormatter(logging.Formatter):
    """自定义 JSON 格式化器"""
    def format(self, record):
        log_record = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }

        # 提取自定义 extra 字段
        if hasattr(record, "request_info"):
            log_record.update(record.request_info)

        # 如果有异常，记录 trace
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_record, ensure_ascii=False)


class TimestampedFormatter(logging.Formatter):
    """Plain timestamped formatter for uvicorn access/error lines."""
    _fmt = "%(asctime)s %(levelname)s %(message)s"
    _datefmt = "%Y-%m-%dT%H:%M:%S"

    def __init__(self):
        super().__init__(fmt=self._fmt, datefmt=self._datefmt)


def setup_uvicorn_logging() -> None:
    """Patch uvicorn's access and error loggers to emit timestamps."""
    fmt = TimestampedFormatter()
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        for handler in uv_logger.handlers:
            handler.setFormatter(fmt)
        # If uvicorn hasn't added handlers yet (imported before server starts),
        # attach a StreamHandler now so the formatter is in place when it does.
        if not uv_logger.handlers:
            h = logging.StreamHandler()
            h.setFormatter(fmt)
            uv_logger.addHandler(h)
            uv_logger.propagate = False


def setup_logger(name="notion_opus"):
    """配置并返回单例全局 logger"""
    logger = logging.getLogger(name)

    # 防止重复添加 handler
    if not logger.handlers:
        logger.setLevel(logging.INFO)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(JsonFormatter())

        logger.addHandler(console_handler)

    return logger


# 全局单例 logger 实例
logger = setup_logger()

# Patch uvicorn loggers at import time so timestamps appear from the first line
setup_uvicorn_logging()

