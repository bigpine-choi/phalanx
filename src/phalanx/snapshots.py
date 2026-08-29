"""Secure, write-once JSON persistence for account snapshots."""

from __future__ import annotations

import os
import secrets
import stat
from contextlib import suppress
from pathlib import Path
from zoneinfo import ZoneInfo

from phalanx.domain import AccountSnapshot

PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
KOREA_TIMEZONE = ZoneInfo("Asia/Seoul")


class SnapshotStorageError(RuntimeError):
    """Base error raised when a snapshot cannot be stored safely."""


class UnsafeSnapshotPathError(SnapshotStorageError):
    """Raised when a snapshot path is unsafe to use."""


class SnapshotAlreadyExistsError(SnapshotStorageError):
    """Raised rather than overwriting an existing snapshot path."""


def _random_identifier() -> str:
    return secrets.token_hex(8)


def _snapshot_filename(snapshot: AccountSnapshot) -> str:
    observed_at = snapshot.query_completed_at.astimezone(KOREA_TIMEZONE).strftime(
        "%Y%m%dT%H%M%S%f%z"
    )
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
    _validate_private_directory_stat(metadata, path)


def _validate_directory_identity(metadata: os.stat_result, path: Path) -> None:
    if not stat.S_ISDIR(metadata.st_mode):
        raise UnsafeSnapshotPathError(f"snapshot directory is not a real directory: {path}")
    if metadata.st_uid != os.geteuid():
        raise UnsafeSnapshotPathError(
            f"snapshot directory must be owned by the current user: {path}"
        )


def _validate_private_directory_stat(metadata: os.stat_result, path: Path) -> None:
    _validate_directory_identity(metadata, path)
    if stat.S_IMODE(metadata.st_mode) != PRIVATE_DIRECTORY_MODE:
        raise UnsafeSnapshotPathError(f"snapshot directory must have mode 0700: {path}")


def _same_file(first: os.stat_result, second: os.stat_result) -> bool:
    return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)


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
        created = False
        try:
            os.mkdir(path, PRIVATE_DIRECTORY_MODE)
            created = True
        except FileExistsError:
            pass

        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = -1
        try:
            before = path.lstat()
            _validate_directory_identity(before, path)
            descriptor = os.open(path, flags)
            opened = os.fstat(descriptor)
            _validate_directory_identity(opened, path)
            if not _same_file(before, opened):
                raise UnsafeSnapshotPathError(
                    f"snapshot directory changed while it was opened: {path}"
                )

            if created:
                os.fchmod(descriptor, PRIVATE_DIRECTORY_MODE)
                opened = os.fstat(descriptor)
            _validate_private_directory_stat(opened, path)
        except UnsafeSnapshotPathError:
            raise
        except OSError:
            raise UnsafeSnapshotPathError(
                f"snapshot directory could not be opened safely: {path}"
            ) from None
        finally:
            if descriptor >= 0:
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


def _store_snapshot(snapshot: AccountSnapshot, snapshot_directory: Path) -> Path:
    payload = _serialize_snapshot(snapshot)
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
            or directory_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(directory_metadata.st_mode) != PRIVATE_DIRECTORY_MODE
        ):
            raise UnsafeSnapshotPathError(
                "snapshot directory must be current-user owned with mode 0700: "
                f"{snapshot_directory}"
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


def default_snapshot_directory() -> Path:
    """Resolve the fixed production snapshot directory at execution time."""

    return Path.home() / ".local" / "share" / "phalanx" / "snapshots"


class SnapshotStore:
    """Persist complete snapshots in one injected or fixed production directory."""

    def __init__(self, directory: Path | None = None) -> None:
        self._application_directories: tuple[Path, ...]
        if directory is None:
            resolved_directory = default_snapshot_directory()
            self._application_directories = (
                resolved_directory.parent,
                resolved_directory,
            )
        else:
            resolved_directory = Path(directory)
            self._application_directories = (resolved_directory,)
        self.directory = resolved_directory

    def save(self, snapshot: AccountSnapshot) -> Path:
        """Atomically persist one already-complete immutable snapshot."""

        prepared_directories = tuple(
            _ensure_private_directory(directory) for directory in self._application_directories
        )
        for directory in prepared_directories:
            _validate_private_directory(directory)
        return _store_snapshot(snapshot, prepared_directories[-1])


def save_snapshot(snapshot: AccountSnapshot, directory: Path | None = None) -> Path:
    """Atomically persist a complete snapshot without following links or overwriting files."""

    return SnapshotStore(directory).save(snapshot)


__all__ = [
    "SnapshotAlreadyExistsError",
    "SnapshotStorageError",
    "SnapshotStore",
    "UnsafeSnapshotPathError",
    "default_snapshot_directory",
    "save_snapshot",
]
