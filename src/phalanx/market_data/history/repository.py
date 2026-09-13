"""Private SQLite storage and process-scoped, nonblocking per-job execution locks."""

from __future__ import annotations

import fcntl
import os
import re
import sqlite3
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from urllib.parse import quote

from pydantic import ValidationError

from phalanx.domain.market_data import DailyBar
from phalanx.domain.price_history import HistoryJob, HistoryView, SymbolHistory
from phalanx.market_data.history.errors import HistoryError, HistoryStorageError
from phalanx.snapshots import (
    SnapshotStorageError,
    _assert_no_symlink_components,
    _ensure_private_directory,
    _open_secure_temporary_file,
    _same_file,
    _validate_private_directory,
)

_APPLICATION_ID = 0x50484831
_SCHEMA = (
    "CREATE TABLE jobs (job_id TEXT PRIMARY KEY, job_json TEXT NOT NULL)",
    "CREATE TABLE symbols (job_id TEXT NOT NULL REFERENCES jobs(job_id), "
    "ordinal INTEGER NOT NULL, state_json TEXT NOT NULL, PRIMARY KEY(job_id, ordinal))",
)


def default_history_path() -> Path:
    if not sys.platform.startswith("linux"):
        raise HistoryStorageError()
    return Path.home() / ".local/share/phalanx/market-data/history.sqlite3"


def _validate_file(path: Path) -> os.stat_result:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        raise HistoryStorageError()
    return metadata


def _initialize(path: Path) -> None:
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    name: str | None = None
    try:
        fd, name = _open_secure_temporary_file(directory, path.name)
        os.close(fd)
        connection = sqlite3.connect(path.parent / name)
        try:
            with connection:
                for statement in _SCHEMA:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version = 1")
                connection.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
        finally:
            connection.close()
        with suppress(FileExistsError):
            os.link(name, path.name, src_dir_fd=directory, dst_dir_fd=directory)
    finally:
        try:
            if name is not None:
                os.unlink(name, dir_fd=directory)
            os.fsync(directory)
        finally:
            os.close(directory)


class SqliteHistoryRepository:
    """Each symbol's bars, hash, attempt outcome and status commit together.

    Reads never create the DB. An execution lock outlives individual connections;
    no SQLite transaction is held while a provider performs network requests.
    Completed results are immutable, including when a stale writer tries again.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = (default_history_path() if path is None else path).absolute()

    def _check_path(self) -> os.stat_result:
        _assert_no_symlink_components(self.path)
        _validate_private_directory(self.path.parent)
        for suffix in ("-journal", "-wal", "-shm"):
            sidecar = self.path.with_name(self.path.name + suffix)
            if sidecar.exists() or sidecar.is_symlink():
                _validate_file(sidecar)
                if suffix != "-journal":
                    raise HistoryStorageError()
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
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            if (
                connection.execute("PRAGMA user_version").fetchone()[0] != 1
                or connection.execute("PRAGMA application_id").fetchone()[0] != _APPLICATION_ID
                or connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete"
            ):
                raise HistoryStorageError()
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            if not _same_file(before, self._check_path()):
                raise HistoryStorageError()
            yield connection
            if not _same_file(before, self._check_path()):
                raise HistoryStorageError()
            connection.commit()
        except (OSError, sqlite3.Error, SnapshotStorageError, ValidationError, ValueError):
            raise HistoryStorageError() from None
        finally:
            if connection is not None:
                connection.close()

    def create(self, view: HistoryView) -> None:
        with self._connect(write=True, create=True) as connection:
            connection.execute(
                "INSERT INTO jobs VALUES (?, ?)", (view.job.job_id, view.job.model_dump_json())
            )
            connection.executemany(
                "INSERT INTO symbols VALUES (?, ?, ?)",
                [(view.job.job_id, s.ordinal, s.model_dump_json()) for s in view.symbols],
            )

    def load(self, job_id: str) -> HistoryView:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT job_json FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise HistoryError(
                    "JOB_NOT_FOUND", "지정한 일봉 작업이 없습니다. create가 필요합니다."
                )
            symbols = connection.execute(
                "SELECT state_json FROM symbols WHERE job_id=? ORDER BY ordinal", (job_id,)
            ).fetchall()
            job = HistoryJob.model_validate_json(row[0])
            if job.job_id != job_id:
                raise HistoryStorageError()
            return HistoryView(
                job=job,
                symbols=tuple(SymbolHistory.model_validate_json(s[0]) for s in symbols),
            )

    def save_symbol(self, job_id: str, before: SymbolHistory, after: SymbolHistory) -> None:
        if before.ordinal != after.ordinal or before.result is not None:
            raise HistoryStorageError()
        with self._connect(write=True) as connection:
            row = connection.execute(
                "SELECT job_json FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise HistoryStorageError()
            job = HistoryJob.model_validate_json(row[0])
            if job.job_id != job_id or after.ordinal >= len(job.targets):
                raise HistoryStorageError()
            if after.result is not None and any(
                bar.stock_code != job.targets[after.ordinal].short_code
                or not job.start <= bar.trade_date <= job.end
                for bar in after.result.bars
            ):
                raise HistoryStorageError()
            update = connection.execute(
                "UPDATE symbols SET state_json=? WHERE job_id=? AND ordinal=? AND state_json=?",
                (after.model_dump_json(), job_id, before.ordinal, before.model_dump_json()),
            )
            if update.rowcount != 1:
                raise HistoryStorageError()

    def read_bars(self, job_id: str, stock_code: str) -> tuple[DailyBar, ...]:
        """Read exact stored bars; an empty completed query returns (), pending raises."""
        _, symbol = self.show(job_id, stock_code)
        if symbol.result is None:
            raise HistoryError("RESULT_NOT_READY", f"저장된 조회 결과가 없습니다: {symbol.status}")
        return symbol.result.bars

    def show(self, job_id: str, stock_code: str) -> tuple[HistoryJob, SymbolHistory]:
        """Validate frozen inputs and only the requested symbol's stored result."""
        job, symbols = self.read_selected(job_id, codes=(stock_code,))
        return job, symbols[0]

    def read_selected(
        self, job_id: str, *, codes: tuple[str, ...] = (), all_targets: bool = False
    ) -> tuple[HistoryJob, tuple[SymbolHistory, ...]]:
        """Read selected states once, in requested order, from one SQLite snapshot."""
        if bool(codes) == all_targets:
            raise HistoryError(
                "TARGET_SELECTION_REQUIRED", "--code 또는 --all-targets 중 하나가 필요합니다."
            )
        if len(codes) != len(set(codes)):
            raise HistoryError("DUPLICATE_CODE", "중복 --code는 허용하지 않습니다.")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT job_json FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise HistoryError(
                    "JOB_NOT_FOUND", "지정한 일봉 작업이 없습니다. create가 필요합니다."
                )
            job = HistoryJob.model_validate_json(row[0])
            if job.job_id != job_id:
                raise HistoryStorageError()
            if all_targets:
                ordinals = tuple(range(len(job.targets)))
            else:
                by_code = {target.short_code: index for index, target in enumerate(job.targets)}
                if any(code not in by_code for code in codes):
                    raise HistoryError(
                        "SYMBOL_NOT_FOUND", "해당 종목은 이 작업의 고정 대상이 아닙니다."
                    )
                ordinals = tuple(by_code[code] for code in codes)
            return job, tuple(self._read_symbol(connection, job, ordinal) for ordinal in ordinals)

    @staticmethod
    def _read_symbol(
        connection: sqlite3.Connection, job: HistoryJob, ordinal: int
    ) -> SymbolHistory:
        row = connection.execute(
            "SELECT state_json FROM symbols WHERE job_id=? AND ordinal=?", (job.job_id, ordinal)
        ).fetchone()
        if row is None:
            raise HistoryStorageError()
        symbol = SymbolHistory.model_validate_json(row[0])
        if symbol.ordinal != ordinal:
            raise HistoryStorageError()
        if symbol.result is not None and any(
            bar.stock_code != job.targets[ordinal].short_code
            or not job.start <= bar.trade_date <= job.end
            for bar in symbol.result.bars
        ):
            raise HistoryStorageError()
        return symbol

    @contextmanager
    def execution_lock(self, job_id: str) -> Iterator[None]:
        if re.fullmatch(r"[0-9a-f]{32}", job_id) is None:
            raise HistoryError("JOB_NOT_FOUND", "유효한 일봉 JOB_ID가 필요합니다.")
        lock_path = self.path.with_name(f"{self.path.name}.{job_id}.lock")
        descriptor: int | None = None
        try:
            self._check_path()
            descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            if not _same_file(os.fstat(descriptor), _validate_file(lock_path)):
                raise HistoryStorageError()
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise HistoryError("JOB_BUSY", "같은 작업이 이미 실행 중입니다.") from None
            if not _same_file(os.fstat(descriptor), _validate_file(lock_path)):
                raise HistoryStorageError()
        except (OSError, SnapshotStorageError):
            if descriptor is not None:
                os.close(descriptor)
                descriptor = None
            raise HistoryStorageError() from None
        except BaseException:
            if descriptor is not None:
                os.close(descriptor)
            raise
        try:
            # A killed SQLite writer may leave a hot rollback journal. Recover it
            # with a short writable connection before attempting read-only loads.
            with self._connect(write=True) as connection:
                if (
                    connection.execute("SELECT 1 FROM jobs WHERE job_id=?", (job_id,)).fetchone()
                    is None
                ):
                    raise HistoryError("JOB_NOT_FOUND", "지정한 일봉 작업이 없습니다.")
            yield
        finally:
            os.close(descriptor)
