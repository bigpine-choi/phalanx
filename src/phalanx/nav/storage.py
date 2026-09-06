"""Private SQLite persistence for append-only NAV inputs and replay history."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import date
from pathlib import Path
from types import TracebackType
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, ValidationError

from phalanx.nav.engine import calculate_daily_nav
from phalanx.nav.models import (
    DailyInput,
    DailyNav,
    Inception,
    InputBundle,
    LedgerEvent,
    NavError,
    parse_bundle_bytes,
)
from phalanx.snapshots import (
    SnapshotStorageError,
    _assert_no_symlink_components,
    _ensure_private_directory,
    _open_secure_temporary_file,
    _same_file,
    _validate_private_directory,
)

_SCHEMA_VERSION = 1
_APPLICATION_ID = 0x504E4156
_ENGINE_VERSION = "1"
_SCHEMA = (
    """CREATE TABLE series (
        environment TEXT NOT NULL CHECK(environment IN ('development', 'official')),
        series_id TEXT NOT NULL,
        inception_json TEXT NOT NULL,
        PRIMARY KEY(environment, series_id)
    )""",
    """CREATE TABLE source_imports (
        import_id INTEGER PRIMARY KEY,
        environment TEXT NOT NULL,
        series_id TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        raw_payload BLOB NOT NULL,
        imported_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        UNIQUE(environment, series_id, sha256),
        FOREIGN KEY(environment, series_id) REFERENCES series(environment, series_id)
    )""",
    """CREATE TABLE event_revisions (
        environment TEXT NOT NULL,
        series_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision > 0),
        event_date TEXT NOT NULL,
        payload TEXT NOT NULL,
        import_id INTEGER NOT NULL REFERENCES source_imports(import_id),
        PRIMARY KEY(environment, series_id, event_id, revision),
        FOREIGN KEY(environment, series_id) REFERENCES series(environment, series_id)
    )""",
    """CREATE TABLE day_revisions (
        environment TEXT NOT NULL,
        series_id TEXT NOT NULL,
        day_date TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision > 0),
        payload TEXT NOT NULL,
        import_id INTEGER NOT NULL REFERENCES source_imports(import_id),
        PRIMARY KEY(environment, series_id, day_date, revision),
        FOREIGN KEY(environment, series_id) REFERENCES series(environment, series_id)
    )""",
    """CREATE TABLE calculation_runs (
        run_id INTEGER PRIMARY KEY,
        environment TEXT NOT NULL,
        series_id TEXT NOT NULL,
        through_date TEXT NOT NULL,
        input_sha256 TEXT NOT NULL,
        input_manifest TEXT NOT NULL,
        engine_version TEXT NOT NULL,
        calculated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        FOREIGN KEY(environment, series_id) REFERENCES series(environment, series_id)
    )""",
    """CREATE TABLE calculation_rows (
        run_id INTEGER NOT NULL REFERENCES calculation_runs(run_id),
        day_date TEXT NOT NULL,
        payload TEXT NOT NULL,
        PRIMARY KEY(run_id, day_date)
    )""",
    """CREATE TABLE daily_nav (
        environment TEXT NOT NULL,
        series_id TEXT NOT NULL,
        day_date TEXT NOT NULL,
        payload TEXT NOT NULL,
        run_id INTEGER NOT NULL REFERENCES calculation_runs(run_id),
        PRIMARY KEY(environment, series_id, day_date),
        FOREIGN KEY(environment, series_id) REFERENCES series(environment, series_id)
    )""",
)


class NavStorageError(NavError):
    """An input conflict, invalid store, or safe persistence failure."""


def _canonical(model: BaseModel) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _validate_private_file(path: Path) -> os.stat_result:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        raise NavStorageError("NAV database and sidecars must be private, unlinked regular files")
    return metadata


def _write_initial_schema(path: Path) -> None:
    """Complete the schema on a private temporary inode before publishing its name."""

    connection = sqlite3.connect(
        f"file:{quote(str(path), safe='/')}?mode=rw", uri=True, isolation_level=None
    )
    try:
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        connection.execute("BEGIN IMMEDIATE")
        for statement in _SCHEMA:
            connection.execute(statement)
        connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        connection.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
        connection.commit()
    finally:
        connection.close()


def _initialize_database(path: Path) -> None:
    """Install a fully initialized database atomically without replacing any existing file."""

    descriptor = os.open(
        path.parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    temporary_name: str | None = None
    try:
        temporary_descriptor, temporary_name = _open_secure_temporary_file(descriptor, path.name)
        os.close(temporary_descriptor)
        _write_initial_schema(path.parent / temporary_name)
        _validate_private_directory(path.parent)
        _validate_private_file(path.parent / temporary_name)
        # Another creator's completed database wins; never replace its settings.
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
                with suppress(FileNotFoundError):
                    os.unlink(temporary_name, dir_fd=descriptor)
        finally:
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)


def _remove_interrupted_install_link(path: Path) -> None:
    """Recover only this store's reserved temporary link after an interrupted install."""

    metadata = path.lstat()
    if metadata.st_nlink <= 1:
        return
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        return
    pattern = re.compile(re.escape(f".{path.name}.") + r"[0-9a-f]{16}\.tmp")
    for candidate in path.parent.iterdir():
        if not pattern.fullmatch(candidate.name):
            continue
        try:
            temporary = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISREG(temporary.st_mode) and _same_file(metadata, temporary):
            with suppress(FileNotFoundError):
                candidate.unlink()


class NavStore:
    """Store explicitly named series without ever choosing an inception date.

    Opening a missing database requires ``create=True``. Existing directories
    and files are checked, never silently chmod-ed. DELETE journaling uses the
    database's 0600 permissions and keeps all files under a private 0700 parent.
    SQLite's write lock serializes imports and complete deterministic replays.
    Path checks reject unsafe files and ordinary replacement; they cannot isolate
    a malicious process running as the same filesystem owner.
    """

    def __init__(self, path: Path, *, create: bool = False) -> None:
        self.path = Path(path).absolute()
        self._connection: sqlite3.Connection | None = None
        self._metadata: os.stat_result | None = None
        try:
            _assert_no_symlink_components(self.path)
            if create:
                _ensure_private_directory(self.path.parent)
            else:
                if not self.path.exists():
                    raise NavStorageError(
                        "NAV database does not exist; import explicit inputs first"
                    )
                _validate_private_directory(self.path.parent)

            self._check_sidecars()
            if create and not self.path.exists():
                _initialize_database(self.path)
            _remove_interrupted_install_link(self.path)
            # Do not open/close an extra descriptor for an existing SQLite file:
            # POSIX close can release this process's other SQLite connections' locks.
            self._metadata = _validate_private_file(self.path)
            self._validate_path()
            self._connection = sqlite3.connect(
                f"file:{quote(str(self.path), safe='/')}?mode=rw",
                uri=True,
                timeout=10,
                isolation_level=None,
            )
            self._connection.row_factory = sqlite3.Row
            self._validate_path()
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA trusted_schema = OFF")
            version = self._connection.execute("PRAGMA user_version").fetchone()[0]
            application = self._connection.execute("PRAGMA application_id").fetchone()[0]
            if version != _SCHEMA_VERSION or application != _APPLICATION_ID:
                raise NavStorageError("unsupported or unrecognized NAV database schema")
            mode = self._connection.execute("PRAGMA journal_mode = DELETE").fetchone()[0]
            if mode != "delete":
                raise NavStorageError("NAV database requires DELETE journaling")
            self._connection.execute("PRAGMA synchronous = FULL")
        except BaseException as error:
            self.close()
            if isinstance(error, NavStorageError):
                raise
            if isinstance(error, (OSError, sqlite3.Error, SnapshotStorageError)):
                raise NavStorageError("could not safely open NAV database") from None
            raise

    def _check_sidecars(self) -> None:
        for suffix in ("-journal", "-wal", "-shm"):
            sidecar = self.path.with_name(self.path.name + suffix)
            try:
                _validate_private_file(sidecar)
            except FileNotFoundError:
                continue
            if suffix != "-journal":
                raise NavStorageError("NAV database has unsupported WAL sidecars")

    def _validate_path(self) -> None:
        _assert_no_symlink_components(self.path)
        _validate_private_directory(self.path.parent)
        metadata = _validate_private_file(self.path)
        if self._metadata is None or not _same_file(metadata, self._metadata):
            raise NavStorageError("NAV database path identity changed")
        self._check_sidecars()

    @contextmanager
    def _transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        if self._connection is None:
            raise NavStorageError("NAV database is closed")
        connection = self._connection
        try:
            self._validate_path()
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            try:
                yield connection
                self._validate_path()
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        except (OSError, sqlite3.Error, SnapshotStorageError, ValidationError, ValueError):
            raise NavStorageError("NAV database operation failed") from None

    def close(self) -> None:
        """Release SQLite, including after a failed open."""

        if self._connection is not None:
            with suppress(sqlite3.Error):
                self._connection.close()
            self._connection = None

    def __enter__(self) -> NavStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    @staticmethod
    def _inception(connection: sqlite3.Connection, series_id: str, environment: str) -> Inception:
        row = connection.execute(
            "SELECT inception_json FROM series WHERE environment = ? AND series_id = ?",
            (environment, series_id),
        ).fetchone()
        if row is None:
            raise NavStorageError("NAV series does not exist in the selected environment")
        return Inception.model_validate_json(row[0])

    def import_bundle(self, bundle: InputBundle, *, raw_payload: bytes) -> dict[str, int]:
        """Atomically append exact sources and revisions; refuse conflicts/resets.

        Any changed input invalidates the complete current derived view. Prior
        calculation runs remain available in history; restoration reconstructs
        the view from the latest input revisions. Missing items are never deletes.
        """

        if not isinstance(raw_payload, bytes):
            raise NavStorageError("original payload must be bytes")
        try:
            original = parse_bundle_bytes(raw_payload)
        except (NavError, ValueError, TypeError):
            raise NavStorageError("original payload is not a valid NAV input bundle") from None
        if _canonical(original) != _canonical(bundle):
            raise NavStorageError("original payload does not match the normalized input bundle")
        identity = (bundle.environment, bundle.series_id)
        stats = dict.fromkeys(
            (
                "created_series",
                "inserted_sources",
                "inserted_events",
                "inserted_days",
                "unchanged_events",
                "unchanged_days",
                "invalidated_days",
            ),
            0,
        )
        with self._transaction(write=True) as connection:
            row = connection.execute(
                "SELECT inception_json FROM series WHERE environment = ? AND series_id = ?",
                identity,
            ).fetchone()
            if row is None:
                if bundle.inception is None:
                    raise NavStorageError("new NAV series requires an explicit inception")
                connection.execute(
                    "INSERT INTO series VALUES (?, ?, ?)", (*identity, _canonical(bundle.inception))
                )
                stats["created_series"] = 1
                inception = bundle.inception
            else:
                inception = Inception.model_validate_json(row[0])
                if bundle.inception is not None and _canonical(bundle.inception) != row[0]:
                    raise NavStorageError(
                        "inception is immutable; create a distinct series to replace it"
                    )

            for event in bundle.events:
                if event.date <= inception.inception_date:
                    raise NavStorageError(
                        "ledger events must occur after the inception closing state"
                    )
            for day in bundle.days:
                if day.date < inception.inception_date:
                    raise NavStorageError("daily inputs cannot precede inception")

            digest = hashlib.sha256(raw_payload).hexdigest()
            source = connection.execute(
                "SELECT import_id FROM source_imports "
                "WHERE environment = ? AND series_id = ? AND sha256 = ?",
                (*identity, digest),
            ).fetchone()
            if source is None:
                cursor = connection.execute(
                    "INSERT INTO source_imports(environment, series_id, sha256, raw_payload) "
                    "VALUES (?, ?, ?, ?)",
                    (*identity, digest, raw_payload),
                )
                import_id = cursor.lastrowid
                stats["inserted_sources"] = 1
            else:
                import_id = source[0]

            for event in bundle.events:
                inserted = self._append_revision(connection, identity, event, import_id)
                stats["inserted_events" if inserted else "unchanged_events"] += 1
            for day in bundle.days:
                inserted = self._append_revision(connection, identity, day, import_id)
                stats["inserted_days" if inserted else "unchanged_days"] += 1

            if stats["inserted_events"] or stats["inserted_days"]:
                cursor = connection.execute(
                    "DELETE FROM daily_nav WHERE environment = ? AND series_id = ?", identity
                )
                stats["invalidated_days"] = cursor.rowcount
        return stats

    @staticmethod
    def _append_revision(
        connection: sqlite3.Connection,
        identity: tuple[str, str],
        value: LedgerEvent | DailyInput,
        import_id: int | None,
    ) -> bool:
        if isinstance(value, LedgerEvent):
            table, key_name, key = "event_revisions", "event_id", value.event_id
        else:
            table, key_name, key = "day_revisions", "day_date", value.date.isoformat()
        payload = _canonical(value)
        rows = connection.execute(
            f"SELECT revision, payload FROM {table} "
            f"WHERE environment = ? AND series_id = ? AND {key_name} = ? ORDER BY revision DESC",
            (*identity, key),
        ).fetchall()
        for row in rows:
            if row[0] == value.revision:
                if row[1] != payload:
                    raise NavStorageError("same input revision has conflicting content")
                return False
        latest_revision = rows[0][0] if rows else 0
        if value.revision != latest_revision + 1:
            raise NavStorageError("input revisions must start at 1 and advance without gaps")
        if isinstance(value, LedgerEvent):
            connection.execute(
                "INSERT INTO event_revisions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (*identity, key, value.revision, value.date.isoformat(), payload, import_id),
            )
        else:
            connection.execute(
                "INSERT INTO day_revisions VALUES (?, ?, ?, ?, ?, ?)",
                (*identity, key, value.revision, payload, import_id),
            )
        return True

    @staticmethod
    def _latest_inputs(
        connection: sqlite3.Connection, identity: tuple[str, str]
    ) -> tuple[tuple[LedgerEvent, ...], tuple[DailyInput, ...]]:
        events = connection.execute(
            """SELECT e.payload FROM event_revisions e
            WHERE e.environment = ? AND e.series_id = ? AND e.revision = (
                SELECT MAX(n.revision) FROM event_revisions n
                WHERE n.environment = e.environment AND n.series_id = e.series_id
                AND n.event_id = e.event_id)
            ORDER BY e.event_date, e.event_id""",
            identity,
        ).fetchall()
        days = connection.execute(
            """SELECT d.payload FROM day_revisions d
            WHERE d.environment = ? AND d.series_id = ? AND d.revision = (
                SELECT MAX(n.revision) FROM day_revisions n
                WHERE n.environment = d.environment AND n.series_id = d.series_id
                AND n.day_date = d.day_date)
            ORDER BY d.day_date""",
            identity,
        ).fetchall()
        return (
            tuple(LedgerEvent.model_validate_json(row[0]) for row in events),
            tuple(DailyInput.model_validate_json(row[0]) for row in days),
        )

    def restore(self, series_id: str, environment: str, through: date) -> tuple[DailyNav, ...]:
        """Replay all calendar days, retaining at least the prior calculation horizon."""

        identity = (environment, series_id)
        with self._transaction(write=True) as connection:
            inception = self._inception(connection, series_id, environment)
            if through < inception.inception_date:
                raise NavStorageError("restoration end cannot precede inception")
            previous = connection.execute(
                "SELECT MAX(through_date) FROM calculation_runs "
                "WHERE environment = ? AND series_id = ?",
                identity,
            ).fetchone()[0]
            horizon = max(through, date.fromisoformat(previous)) if previous else through
            events, days = self._latest_inputs(connection, identity)
            results = calculate_daily_nav(inception, events, days, through=horizon)
            input_json = json.dumps(
                {
                    "inception": inception.model_dump(mode="json"),
                    "events": [event.model_dump(mode="json") for event in events],
                    "days": [day.model_dump(mode="json") for day in days],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            input_digest = hashlib.sha256(input_json.encode()).hexdigest()
            cursor = connection.execute(
                "INSERT INTO calculation_runs(environment, series_id, through_date, "
                "input_sha256, input_manifest, engine_version) VALUES (?, ?, ?, ?, ?, ?)",
                (*identity, horizon.isoformat(), input_digest, input_json, _ENGINE_VERSION),
            )
            run_id = cursor.lastrowid
            connection.execute(
                "DELETE FROM daily_nav WHERE environment = ? AND series_id = ?", identity
            )
            for result in results:
                payload = _canonical(result)
                connection.execute(
                    "INSERT INTO calculation_rows VALUES (?, ?, ?)",
                    (run_id, result.date.isoformat(), payload),
                )
                connection.execute(
                    "INSERT INTO daily_nav VALUES (?, ?, ?, ?, ?)",
                    (*identity, result.date.isoformat(), payload, run_id),
                )
        return results

    def query(self, series_id: str, environment: str) -> tuple[DailyNav, ...]:
        """Return the current derived view; invalidated outputs are never served."""

        with self._transaction() as connection:
            self._inception(connection, series_id, environment)
            rows = connection.execute(
                "SELECT payload FROM daily_nav WHERE environment = ? AND series_id = ? "
                "ORDER BY day_date",
                (environment, series_id),
            ).fetchall()
            return tuple(DailyNav.model_validate_json(row[0]) for row in rows)

    def history(self, series_id: str, environment: str) -> dict[str, Any]:
        """Return base64-encoded exact sources and every accepted input/calculation revision."""

        identity = (environment, series_id)
        with self._transaction() as connection:
            inception = self._inception(connection, series_id, environment)
            sources = connection.execute(
                "SELECT import_id, sha256, raw_payload, imported_at FROM source_imports "
                "WHERE environment = ? AND series_id = ? ORDER BY import_id",
                identity,
            ).fetchall()
            events = connection.execute(
                "SELECT import_id, payload FROM event_revisions "
                "WHERE environment = ? AND series_id = ? ORDER BY event_id, revision",
                identity,
            ).fetchall()
            days = connection.execute(
                "SELECT import_id, payload FROM day_revisions "
                "WHERE environment = ? AND series_id = ? ORDER BY day_date, revision",
                identity,
            ).fetchall()
            runs = connection.execute(
                "SELECT run_id, through_date, input_sha256, input_manifest, "
                "engine_version, calculated_at "
                "FROM calculation_runs WHERE environment = ? AND series_id = ? ORDER BY run_id",
                identity,
            ).fetchall()
            calculations = []
            for run in runs:
                outputs = connection.execute(
                    "SELECT payload FROM calculation_rows WHERE run_id = ? ORDER BY day_date",
                    (run["run_id"],),
                ).fetchall()
                calculations.append(
                    {
                        **dict(run),
                        "input_manifest": json.loads(run["input_manifest"]),
                        "days": [json.loads(row[0]) for row in outputs],
                    }
                )
            return {
                "series_id": series_id,
                "environment": environment,
                "inception": inception.model_dump(mode="json"),
                "source_imports": [
                    {
                        "import_id": row["import_id"],
                        "sha256": row["sha256"],
                        "imported_at": row["imported_at"],
                        "raw_payload_base64": base64.b64encode(row["raw_payload"]).decode("ascii"),
                    }
                    for row in sources
                ],
                "events": [{"import_id": row[0], "input": json.loads(row[1])} for row in events],
                "days": [{"import_id": row[0], "input": json.loads(row[1])} for row in days],
                "calculations": calculations,
            }


__all__ = ["NavStorageError", "NavStore"]
