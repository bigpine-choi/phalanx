"""Read-only Windows adapter for closed, local history database exports.

The source is never created, repaired, migrated or written. Native handles pin
all path components and deny source writes/deletion for the whole transaction.
Live databases and every SQLite sidecar are rejected: transfer with SQLite's
backup API, then close and transfer the completed backup.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import ValidationError

from phalanx.domain.price_history import HistoryJob, SymbolHistory
from phalanx.market_data.history.errors import HistoryStorageError
from phalanx.market_data.history.reader import (
    read_selected,
    validate_database,
    validate_selection,
)
from phalanx.platforms.windows_files import guard_local_file


class WindowsHistoryRepository:
    """Only the shared selected-read contract, with no write or default-path API."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _reject_sidecars(self) -> None:
        for suffix in ("-journal", "-wal", "-shm"):
            try:
                self.path.with_name(self.path.name + suffix).lstat()
            except FileNotFoundError:
                continue
            raise HistoryStorageError()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            with guard_local_file(self.path) as guarded:
                self._reject_sidecars()
                # The native guard denies writes and replacement, making SQLite's
                # immutable contract true. Avoid probing a sidecar that an external
                # process could introduce after our absence check. Check the real
                # header because immutable mode itself reports journal_mode=delete.
                with guarded.path.open("rb") as source:
                    header = source.read(100)
                if (
                    len(header) != 100
                    or header[:16] != b"SQLite format 3\x00"
                    or header[18:20] != b"\x01\x01"
                ):
                    raise HistoryStorageError()
                try:
                    connection = sqlite3.connect(
                        guarded.path.as_uri() + "?mode=ro&immutable=1",
                        uri=True,
                        timeout=10,
                        isolation_level=None,
                    )
                    connection.execute("PRAGMA query_only = ON")
                    connection.execute("PRAGMA trusted_schema = OFF")
                    connection.execute("PRAGMA foreign_keys = ON")
                    connection.execute("BEGIN")
                    validate_database(connection)
                    yield connection
                    self._reject_sidecars()
                    connection.rollback()
                finally:
                    # SQLite must release its handles before the native path guard.
                    if connection is not None:
                        connection.close()
        except (OSError, sqlite3.Error, ValidationError, ValueError):
            raise HistoryStorageError() from None

    def read_selected(
        self, job_id: str, *, codes: tuple[str, ...] = (), all_targets: bool = False
    ) -> tuple[HistoryJob, tuple[SymbolHistory, ...]]:
        validate_selection(codes, all_targets)
        with self._connect() as connection:
            return read_selected(connection, job_id, codes=codes, all_targets=all_targets)
