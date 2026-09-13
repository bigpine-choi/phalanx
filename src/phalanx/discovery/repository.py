"""Private SQLite run journal and atomic snapshots, including exact source-file bytes."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from pydantic import ValidationError

from phalanx.discovery.errors import DiscoveryError, DiscoveryStorageError
from phalanx.domain.discovery import Attempt, DiscoveryView, Market, Snapshot
from phalanx.snapshots import (
    SnapshotStorageError,
    _assert_no_symlink_components,
    _ensure_private_directory,
    _open_secure_temporary_file,
    _same_file,
    _validate_private_directory,
)

Artifacts = Mapping[tuple[Market, str], bytes]
_APPLICATION_ID = 0x50444331
_SCHEMA = (
    """CREATE TABLE runs (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT UNIQUE NOT NULL,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        status TEXT NOT NULL,
        snapshot_json TEXT
    )""",
    """CREATE TABLE source_files (
        run_id TEXT NOT NULL REFERENCES runs(run_id),
        market TEXT NOT NULL,
        filename TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        payload BLOB NOT NULL,
        PRIMARY KEY (run_id, market, filename)
    )""",
)


class DiscoveryRepository(Protocol):
    path: Path

    def begin(self, run_id: str, started_at: datetime) -> None: ...

    def save(self, snapshot: Snapshot, artifacts: Artifacts) -> None: ...

    def storage_failed(self, run_id: str, completed_at: datetime) -> None: ...

    def load(self) -> DiscoveryView: ...


def default_discovery_path() -> Path:
    if not sys.platform.startswith("linux"):
        raise DiscoveryStorageError()
    return Path.home() / ".local" / "share" / "phalanx" / "discovery" / "discovery.sqlite3"


def _validate_file(path: Path) -> os.stat_result:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        raise DiscoveryStorageError()
    return metadata


def _initialize(path: Path) -> None:
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary_name: str | None = None
    try:
        fd, temporary_name = _open_secure_temporary_file(descriptor, path.name)
        os.close(fd)
        connection = sqlite3.connect(path.parent / temporary_name)
        try:
            with connection:
                for statement in _SCHEMA:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version = 1")
                connection.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
        finally:
            connection.close()
        with suppress(FileExistsError):
            os.link(
                temporary_name,
                path.name,
                src_dir_fd=descriptor,
                dst_dir_fd=descriptor,
                follow_symlinks=False,
            )
    finally:
        try:
            if temporary_name is not None:
                os.unlink(temporary_name, dir_fd=descriptor)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class SqliteDiscoveryRepository:
    """Every result and all its source bytes commit in one transaction.

    A separately committed start journal exposes interruption or failed writes.
    Readers use SQLite read transactions and never create or update the store.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = (default_discovery_path() if path is None else path).absolute()

    def _check_path(self) -> os.stat_result:
        _assert_no_symlink_components(self.path)
        _validate_private_directory(self.path.parent)
        for suffix in ("-journal", "-wal", "-shm"):
            sidecar = self.path.with_name(self.path.name + suffix)
            if sidecar.exists() or sidecar.is_symlink():
                _validate_file(sidecar)
                if suffix != "-journal":
                    raise DiscoveryStorageError()
        return _validate_file(self.path)

    @contextmanager
    def _connect(
        self, *, write: bool = False, create: bool = False
    ) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            _assert_no_symlink_components(self.path)
            if create:
                _ensure_private_directory(self.path.parent)
                if not self.path.exists():
                    _initialize(self.path)
            before = self._check_path()
            mode = "rw" if write else "ro"
            connection = sqlite3.connect(
                f"file:{quote(str(self.path), safe='/')}?mode={mode}",
                uri=True,
                timeout=10,
                isolation_level=None,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            if (
                connection.execute("PRAGMA user_version").fetchone()[0] != 1
                or connection.execute("PRAGMA application_id").fetchone()[0] != _APPLICATION_ID
            ):
                raise DiscoveryStorageError()
            if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise DiscoveryStorageError()
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            if not _same_file(before, self._check_path()):
                raise DiscoveryStorageError()
            yield connection
            if not _same_file(before, self._check_path()):
                raise DiscoveryStorageError()
            connection.commit()
        except (OSError, sqlite3.Error, SnapshotStorageError, ValidationError, ValueError):
            raise DiscoveryStorageError() from None
        finally:
            if connection is not None:
                connection.close()  # rolls back any unfinished transaction

    def begin(self, run_id: str, started_at: datetime) -> None:
        with self._connect(write=True, create=True) as connection:
            connection.execute(
                "INSERT INTO runs(run_id, started_at, status) VALUES (?, ?, 'in_progress')",
                (run_id, started_at.isoformat()),
            )

    def save(self, snapshot: Snapshot, artifacts: Artifacts) -> None:
        expected = {(m.market, s.filename): s for m in snapshot.markets for s in m.sources}
        if expected.keys() != artifacts.keys() or any(
            expected[key].sha256 != hashlib.sha256(payload).hexdigest()
            or expected[key].size_bytes != len(payload)
            for key, payload in artifacts.items()
        ):
            raise DiscoveryStorageError()
        with self._connect(write=True) as connection:
            for (market, filename), payload in artifacts.items():
                connection.execute(
                    "INSERT INTO source_files VALUES (?, ?, ?, ?, ?)",
                    (
                        snapshot.run_id,
                        market.value,
                        filename,
                        expected[(market, filename)].sha256,
                        payload,
                    ),
                )
            updated = connection.execute(
                "UPDATE runs SET completed_at=?, status=?, snapshot_json=? "
                "WHERE run_id=? AND status='in_progress'",
                (
                    snapshot.collection_completed_at.isoformat(),
                    snapshot.status,
                    snapshot.model_dump_json(),
                    snapshot.run_id,
                ),
            )
            if updated.rowcount != 1:
                raise DiscoveryStorageError()

    def storage_failed(self, run_id: str, completed_at: datetime) -> None:
        with self._connect(write=True) as connection:
            connection.execute(
                "UPDATE runs SET status='storage_failed', completed_at=? "
                "WHERE run_id=? AND status='in_progress'",
                (completed_at.isoformat(), run_id),
            )

    def load(self) -> DiscoveryView:
        try:
            _assert_no_symlink_components(self.path)
            if not self.path.exists():
                return DiscoveryView(latest_attempt=None, snapshot=None)
        except (OSError, SnapshotStorageError):
            raise DiscoveryStorageError() from None
        with self._connect() as connection:
            latest = connection.execute(
                "SELECT * FROM runs ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            if latest is None:
                return DiscoveryView(latest_attempt=None, snapshot=None)
            row = connection.execute(
                "SELECT * FROM runs WHERE status='success' ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            if row is None:
                row = connection.execute(
                    "SELECT * FROM runs WHERE snapshot_json IS NOT NULL "
                    "ORDER BY sequence DESC LIMIT 1"
                ).fetchone()
            snapshot = None if row is None else Snapshot.model_validate_json(row["snapshot_json"])
            if snapshot is not None and (
                snapshot.run_id != row["run_id"] or snapshot.status != row["status"]
            ):
                raise DiscoveryStorageError()
            return DiscoveryView(
                latest_attempt=Attempt(
                    run_id=latest["run_id"],
                    started_at=latest["started_at"],
                    completed_at=latest["completed_at"],
                    status=latest["status"],
                ),
                snapshot=snapshot,
                latest_snapshot=(
                    None
                    if latest["snapshot_json"] is None
                    else Snapshot.model_validate_json(latest["snapshot_json"])
                ),
            )

    def read_source(self, run_id: str, market: Market, filename: str) -> bytes:
        """Recover and integrity-check an exact original ZIP or MST without network access."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload, sha256 FROM source_files "
                "WHERE run_id=? AND market=? AND filename=?",
                (run_id, market.value, filename),
            ).fetchone()
            if row is None:
                raise DiscoveryStorageError()
            payload = bytes(row["payload"])
            if hashlib.sha256(payload).hexdigest() != row["sha256"]:
                raise DiscoveryStorageError()
            return payload

    def load_successful_run(self, run_id: str) -> Snapshot:
        """Read exactly the requested completed run; never fall back to another run."""
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise DiscoveryError("RUN_NOT_FOUND", "지정한 discovery 실행이 없습니다.")
            if row["status"] != "success" or row["snapshot_json"] is None:
                raise DiscoveryError("RUN_NOT_SUCCESSFUL", "성공한 discovery 실행이 필요합니다.")
            snapshot = Snapshot.model_validate_json(row["snapshot_json"])
            if snapshot.run_id != run_id or snapshot.status != "success":
                raise DiscoveryStorageError()
            return snapshot
