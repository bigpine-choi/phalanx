"""Private, write-once atomic storage for already serialized JSON bytes."""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from filelock import FileLock
from filelock import Timeout as FileLockTimeout

_PRIVATE_FILE_MODE = 0o600
_PRIVATE_DIRECTORY_MODE = 0o700
_LOCK_TIMEOUT_SECONDS = 10.0

PathExists = Callable[[Path], bool]
Link = Callable[[Path, Path], None]
TokenHex = Callable[[int], str]
WriteAll = Callable[[int, bytes], None]
FsyncDirectory = Callable[[Path], None]


class PrivateJsonStorageError(Exception):
    """Base failure while privately storing already serialized JSON bytes."""


class PrivateJsonDirectoryError(PrivateJsonStorageError):
    """Raised when the output directory cannot be created safely."""


class PrivateJsonLockError(PrivateJsonStorageError):
    """Raised when the output-specific file lock cannot be used safely."""


class PrivateJsonLockTimeoutError(PrivateJsonLockError):
    """Raised when acquiring the output-specific lock times out."""


class PrivateJsonAlreadyExistsError(PrivateJsonStorageError):
    """Raised rather than replacing an existing output path."""


def store_private_json_bytes(
    output_path: Path,
    payload: bytes,
    *,
    lock_timeout: float = _LOCK_TIMEOUT_SECONDS,
    path_exists: PathExists | None = None,
    link: Link | None = None,
    token_hex: TokenHex | None = None,
    write_all: WriteAll | None = None,
    fsync_directory: FsyncDirectory | None = None,
) -> Path:
    """Atomically store exact JSON bytes once under an output-specific lock.

    The dependency hooks preserve testability for registries that already expose
    their filesystem helpers as monkeypatch boundaries. They do not transform,
    validate, or re-serialize ``payload``.
    """

    if not isinstance(payload, bytes):
        raise PrivateJsonStorageError("private JSON payload must be bytes")

    target = Path(output_path)
    parent = target.parent
    try:
        parent.mkdir(mode=_PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
    except OSError:
        raise PrivateJsonDirectoryError("private JSON output directory creation failed") from None

    selected_path_exists = _path_exists if path_exists is None else path_exists
    selected_link = os.link if link is None else link
    selected_token_hex = secrets.token_hex if token_hex is None else token_hex
    selected_write_all = _write_all if write_all is None else write_all
    selected_fsync_directory = _fsync_directory if fsync_directory is None else fsync_directory

    lock_path = parent / f".{target.name}.lock"
    lock = FileLock(lock_path, timeout=lock_timeout, mode=_PRIVATE_FILE_MODE)
    try:
        with lock:
            os.chmod(lock_path, _PRIVATE_FILE_MODE, follow_symlinks=False)
            return _save_locked(
                target,
                payload,
                path_exists=selected_path_exists,
                link=selected_link,
                token_hex=selected_token_hex,
                write_all=selected_write_all,
                fsync_directory=selected_fsync_directory,
            )
    except FileLockTimeout:
        raise PrivateJsonLockTimeoutError("private JSON output lock timed out") from None
    except PrivateJsonStorageError:
        raise
    except OSError:
        raise PrivateJsonLockError("private JSON output lock failed") from None


def _save_locked(
    output_path: Path,
    payload: bytes,
    *,
    path_exists: PathExists,
    link: Link,
    token_hex: TokenHex,
    write_all: WriteAll,
    fsync_directory: FsyncDirectory,
) -> Path:
    if path_exists(output_path):
        raise PrivateJsonAlreadyExistsError("private JSON output already exists")

    temporary_path = output_path.parent / (f".{output_path.name}.{token_hex(8)}.tmp")
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
        write_all(descriptor, payload)
        os.close(descriptor)
        descriptor = None

        if path_exists(output_path):
            raise PrivateJsonAlreadyExistsError("private JSON output already exists")
        try:
            link(temporary_path, output_path)
        except FileExistsError:
            raise PrivateJsonAlreadyExistsError("private JSON output already exists") from None
        temporary_path.unlink()
        temporary_exists = False
        fsync_directory(output_path.parent)
        return output_path
    except PrivateJsonStorageError:
        raise
    except OSError:
        raise PrivateJsonStorageError("private JSON atomic write failed") from None
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
            raise OSError("private JSON write made no progress")
        remaining = remaining[written:]
    os.fsync(descriptor)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(
        directory,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "PrivateJsonAlreadyExistsError",
    "PrivateJsonDirectoryError",
    "PrivateJsonLockError",
    "PrivateJsonLockTimeoutError",
    "PrivateJsonStorageError",
    "store_private_json_bytes",
]
