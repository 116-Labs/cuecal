"""Single-instance process lock to prevent overlapping runs."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from types import TracebackType
from typing import IO, Any

from . import paths

logger = logging.getLogger("cuecal.lock")


class LockContentionError(Exception):
    """Raised when another cuecal instance holds the single-instance lock."""


class SingleInstanceLock:
    """Non-blocking file lock ensuring only one cuecal run executes at a time."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or paths.lock_path()
        self._file: IO[str] | Any | None = None
        self._locked = False

    def acquire(self) -> bool:
        """Acquire the lock non-blockingly. Returns True if acquired, False on contention."""
        if self._locked:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            f = open(self.path, "a+", encoding="utf-8")
            if sys.platform == "win32":
                import msvcrt

                try:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    f.close()
                    return False
            else:
                import fcntl

                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except (BlockingIOError, OSError):
                    f.close()
                    return False

            self._file = f
            self._locked = True
            try:
                self._file.seek(0)
                self._file.truncate()
                self._file.write(f"{os.getpid()}\n")
                self._file.flush()
            except Exception:
                pass
            return True
        except Exception as exc:
            logger.debug("Failed to acquire lock at %s: %s", self.path, exc)
            if self._file:
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None
            return False

    def release(self) -> None:
        """Release the held lock and close the underlying file."""
        if not self._locked or self._file is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                try:
                    self._file.seek(0)
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                try:
                    fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            self._file.close()
        finally:
            self._file = None
            self._locked = False

    def __enter__(self) -> SingleInstanceLock:
        if not self.acquire():
            raise LockContentionError(f"Another cuecal instance holds lock at {self.path}")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.release()
