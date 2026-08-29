"""Secure, write-once JSON persistence for account snapshots."""

from __future__ import annotations

import os
import secrets
import stat
from contextlib import suppress
from pathlib import Path

from phalanx.domain import AccountSnapshot

DEFAULT_SNAPSHOT_DIRECTORY = Path("runtime/snapshots")
PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


class SnapshotStorageError(RuntimeError):
    """Base error raised when a snapshot cannot be stored safely."""


class UnsafeSnapshotPathError(SnapshotStorageError):
    """Raised when a snapshot path is unsafe to use."""


class SnapshotAlreadyExistsError(SnapshotStorageError):
    """Raised rather than overwriting an existing snapshot path."""


def _random_identifier() -> str:
    return secrets.token_hex(8)


def _snapshot_filename(snapshot: AccountSnapshot) -> str:
    observed_at = snapshot.query_completed_at.strftime("%Y%m%dT%H%M%S%f%z")
    return f"account_snapshot_{observed_at}_{_random_identifier()}.json"


def _assert_no_symlink_components(path: Path) -> None:
    for candidate in (path, *path.parents):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise UnsafeSnapshotPathError(
                f"snapshot path must not contain symbolic links: {candidate}"
            )


def _validate_private_directory(path: Path) -> None:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise UnsafeSnapshotPathError(f"snapshot directory is not a real directory: {path}")
    if stat.S_IMODE(metadata.st_mode) != PRIVATE_DIRECTORY_MODE:
        raise UnsafeSnapshotPathError(f"snapshot directory must have mode 0700: {path}")


def _ensure_private_directory(directory: Path) -> Path:
    absolute_directory = directory.absolute()
    _assert_no_symlink_components(absolute_directory)

    missing: list[Path] = []
    current = absolute_directory
    while not current.exists():
        missing.append(current)
        parent = current.parent
        if parent == current:
            raise UnsafeSnapshotPathError(
                f"cannot find an existing parent for snapshot directory: {directory}"
            )
        current = parent

    if current.is_symlink() or not current.is_dir():
        raise UnsafeSnapshotPathError(f"unsafe snapshot directory parent: {current}")

    for path in reversed(missing):
        with suppress(FileExistsError):
            os.mkdir(path, PRIVATE_DIRECTORY_MODE)

        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            os.fchmod(descriptor, PRIVATE_DIRECTORY_MODE)
        finally:
            os.close(descriptor)

    _assert_no_symlink_components(absolute_directory)
    _validate_private_directory(absolute_directory)
    return absolute_directory


def _open_secure_temporary_file(directory_descriptor: int, final_name: str) -> tuple[int, str]:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    for _ in range(10):
        temporary_name = f".{final_name}.{secrets.token_hex(8)}.tmp"
        try:
            descriptor = os.open(
                temporary_name,
                flags,
                PRIVATE_FILE_MODE,
                dir_fd=directory_descriptor,
            )
        except FileExistsError:
            continue
        os.fchmod(descriptor, PRIVATE_FILE_MODE)
        return descriptor, temporary_name
    raise SnapshotStorageError("could not allocate a unique temporary snapshot file")


def _write_payload(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("snapshot write made no progress")
        remaining = remaining[written:]
    os.fsync(descriptor)


def _serialize_snapshot(snapshot: AccountSnapshot) -> bytes:
    serialized = snapshot.model_dump_json(indent=2)
    return f"{serialized}\n".encode()


def save_snapshot(
    snapshot: AccountSnapshot,
    directory: Path = DEFAULT_SNAPSHOT_DIRECTORY,
) -> Path:
    """Atomically persist a complete snapshot without following links or overwriting files."""

    payload = _serialize_snapshot(snapshot)
    snapshot_directory = _ensure_private_directory(directory)
    final_name = _snapshot_filename(snapshot)
    final_path = snapshot_directory / final_name

    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_descriptor = -1
    file_descriptor = -1
    temporary_name: str | None = None
    final_linked = False
    succeeded = False

    try:
        directory_descriptor = os.open(snapshot_directory, directory_flags)
        directory_metadata = os.fstat(directory_descriptor)
        if (
            not stat.S_ISDIR(directory_metadata.st_mode)
            or stat.S_IMODE(directory_metadata.st_mode) != PRIVATE_DIRECTORY_MODE
        ):
            raise UnsafeSnapshotPathError(
                f"snapshot directory must be a real directory with mode 0700: {snapshot_directory}"
            )

        file_descriptor, temporary_name = _open_secure_temporary_file(
            directory_descriptor, final_name
        )
        _write_payload(file_descriptor, payload)
        os.close(file_descriptor)
        file_descriptor = -1

        try:
            os.link(
                temporary_name,
                final_name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileExistsError as error:
            raise SnapshotAlreadyExistsError(
                f"refusing to overwrite existing snapshot: {final_path}"
            ) from error
        final_linked = True

        os.unlink(temporary_name, dir_fd=directory_descriptor)
        temporary_name = None
        os.fsync(directory_descriptor)
        succeeded = True
        return final_path
    except SnapshotStorageError:
        raise
    except OSError as error:
        raise SnapshotStorageError(f"could not safely store snapshot: {final_path}") from error
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if directory_descriptor >= 0:
            if not succeeded and final_linked:
                with suppress(FileNotFoundError):
                    os.unlink(final_name, dir_fd=directory_descriptor)
            if temporary_name is not None:
                with suppress(FileNotFoundError):
                    os.unlink(temporary_name, dir_fd=directory_descriptor)
            os.close(directory_descriptor)


__all__ = [
    "DEFAULT_SNAPSHOT_DIRECTORY",
    "SnapshotAlreadyExistsError",
    "SnapshotStorageError",
    "UnsafeSnapshotPathError",
    "save_snapshot",
]
