"""Structured (key=value) logging to stderr."""

from __future__ import annotations

import logging
import sys

_STANDARD = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        parts = [
            f"ts={self.formatTime(record, '%Y-%m-%dT%H:%M:%S')}",
            f"level={record.levelname.lower()}",
            f"logger={record.name}",
            f"msg={record.message!r}",
        ]
        parts += [f"{k}={v!r}" for k, v in record.__dict__.items() if k not in _STANDARD]
        if record.exc_info:
            parts.append(f'exc="{self.formatException(record.exc_info)}"')
        return " ".join(parts)


def configure(verbose: bool = False) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(KeyValueFormatter())
    root = logging.getLogger("cuecal")
    root.handlers[:] = [handler]
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
