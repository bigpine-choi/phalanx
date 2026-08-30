"""Private, no-overwrite atomic storage for self-contained HTML reports."""

from __future__ import annotations

import os
import secrets
from contextlib import suppress
from pathlib import Path

from filelock import FileLock
from filelock import Timeout as FileLockTimeout

from phalanx.portfolio.errors import (
    HistoricalReportAlreadyExistsError,
    HistoricalReportLockTimeoutError,
    HistoricalReportStorageError,
)

_PRIVATE_FILE_MODE = 0o600
_PRIVATE_DIRECTORY_MODE = 0o700
_LOCK_TIMEOUT_SECONDS = 10


class HistoricalReportStore:
    """Store one already-rendered HTML document without overwriting a target."""

    def __init__(self, output_path: Path, *, lock_timeout: float = _LOCK_TIMEOUT_SECONDS) -> None:
        self.output_path = Path(output_path)
        self.lock_timeout = lock_timeout

    def save(self, html: str) -> Path:
        """Atomically save private UTF-8 HTML under an output-specific lock."""

        if not isinstance(html, str):
            raise HistoricalReportStorageError("HTML 리포트 내용은 문자열이어야 합니다.")
        parent = self.output_path.parent
        try:
            parent.mkdir(mode=_PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
        except OSError:
            raise HistoricalReportStorageError(
                "HTML 리포트 출력 디렉터리를 만들 수 없습니다."
            ) from None

        lock_path = parent / f".{self.output_path.name}.lock"
        lock = FileLock(lock_path, timeout=self.lock_timeout, mode=_PRIVATE_FILE_MODE)
        try:
            with lock:
                os.chmod(lock_path, _PRIVATE_FILE_MODE, follow_symlinks=False)
                return self._save_locked(html.encode("utf-8"))
        except FileLockTimeout:
            raise HistoricalReportLockTimeoutError(
                "HTML 리포트 출력 파일 잠금을 기다리는 시간이 초과되었습니다."
            ) from None
        except HistoricalReportStorageError:
            raise
        except OSError:
            raise HistoricalReportStorageError(
                "HTML 리포트 파일 잠금을 안전하게 사용할 수 없습니다."
            ) from None

    def _save_locked(self, payload: bytes) -> Path:
        if _path_exists(self.output_path):
            raise HistoricalReportAlreadyExistsError(
                f"기존 HTML 리포트를 덮어쓰지 않습니다: {self.output_path}"
            )

        temporary_path = self.output_path.parent / (
            f".{self.output_path.name}.{secrets.token_hex(8)}.tmp"
        )
        descriptor: int | None = None
        temporary_exists = False
        try:
            descriptor = os.open(
                temporary_path,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                _PRIVATE_FILE_MODE,
            )
            temporary_exists = True
            os.fchmod(descriptor, _PRIVATE_FILE_MODE)
            _write_all(descriptor, payload)
            os.close(descriptor)
            descriptor = None

            if _path_exists(self.output_path):
                raise HistoricalReportAlreadyExistsError(
                    f"기존 HTML 리포트를 덮어쓰지 않습니다: {self.output_path}"
                )
            os.replace(temporary_path, self.output_path)
            temporary_exists = False
            _fsync_directory(self.output_path.parent)
            return self.output_path
        except HistoricalReportStorageError:
            raise
        except OSError:
            raise HistoricalReportStorageError(
                f"HTML 리포트를 원자적으로 저장하지 못했습니다: {self.output_path}"
            ) from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary_exists:
                with suppress(FileNotFoundError):
                    temporary_path.unlink()


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("report write made no progress")
        remaining = remaining[written:]
    os.fsync(descriptor)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(
        directory,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def save_historical_report(html: str, output_path: Path) -> Path:
    """Convenience boundary for private, atomic report persistence."""

    return HistoricalReportStore(output_path).save(html)


__all__ = ["HistoricalReportStore", "save_historical_report"]
