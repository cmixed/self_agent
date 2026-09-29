"""日志配置。

日志字段约定见 AGENTS.md §21：task_id / user_id / node / event / duration /
status / error_type。严禁记录 API Key、Authorization Header 或完整敏感数据。
"""

from __future__ import annotations

import logging

from app.core.config import get_settings

# 允许作为结构化字段附加到 LogRecord 上的键
_STRUCTURED_KEYS = ("task_id", "user_id", "node", "event", "duration", "status", "error_type")


class KeyValueFormatter(logging.Formatter):
    """轻量 key=value 格式化器，便于日志检索，且不会输出敏感字段。"""

    def format(self, record: logging.LogRecord) -> str:
        parts = [
            f"level={record.levelname}",
            f"logger={record.name}",
            f"msg={record.getMessage()}",
        ]
        for key in _STRUCTURED_KEYS:
            value = getattr(record, key, None)
            if value is not None:
                parts.append(f"{key}={value}")
        line = " ".join(parts)
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


def configure_logging() -> None:
    """配置根 logger。重复调用是安全的。"""
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    handler = logging.StreamHandler()
    handler.setFormatter(KeyValueFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
