from __future__ import annotations

import logging
from collections import deque
from threading import Lock
from typing import Deque

_DEFAULT_MAX_RECORDS = 400
_LOG_BUFFER: Deque[str] = deque(maxlen=_DEFAULT_MAX_RECORDS)
_LOCK = Lock()
_HANDLER: logging.Handler | None = None


class _RingBufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:
            try:
                message = record.getMessage()
            except Exception:
                message = str(record)
        with _LOCK:
            _LOG_BUFFER.append(message)


def install_log_buffer(max_records: int = _DEFAULT_MAX_RECORDS) -> None:
    global _HANDLER, _LOG_BUFFER
    if _HANDLER is not None:
        return
    try:
        max_records = int(max_records)
    except Exception:
        max_records = _DEFAULT_MAX_RECORDS
    max_records = max(100, max_records)
    _LOG_BUFFER = deque(maxlen=max_records)
    handler = _RingBufferHandler()
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logging.getLogger().addHandler(handler)
    _HANDLER = handler


def get_log_buffer_text(max_lines: int = 200) -> str:
    if max_lines is None:
        max_lines = 0
    try:
        max_lines = int(max_lines)
    except Exception:
        max_lines = 200
    with _LOCK:
        lines = list(_LOG_BUFFER)
    if max_lines > 0:
        lines = lines[-max_lines:]
    return "\n".join(lines).strip()
