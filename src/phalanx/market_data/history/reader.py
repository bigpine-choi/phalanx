"""Shared, platform-independent validation for a frozen history SQLite snapshot."""

from __future__ import annotations

import sqlite3
from typing import Protocol

from phalanx.domain.price_history import HistoryJob, SymbolHistory
from phalanx.market_data.history.errors import HistoryError, HistoryStorageError

APPLICATION_ID = 0x50484831
SCHEMA = (
    "CREATE TABLE jobs (job_id TEXT PRIMARY KEY, job_json TEXT NOT NULL)",
    "CREATE TABLE symbols (job_id TEXT NOT NULL REFERENCES jobs(job_id), "
    "ordinal INTEGER NOT NULL, state_json TEXT NOT NULL, PRIMARY KEY(job_id, ordinal))",
)


class HistoryReader(Protocol):
    """Only the read contract required by offline allocation preparation."""

    def read_selected(
        self, job_id: str, *, codes: tuple[str, ...] = (), all_targets: bool = False
    ) -> tuple[HistoryJob, tuple[SymbolHistory, ...]]: ...


def validate_database(connection: sqlite3.Connection, *, strict_schema: bool = True) -> None:
    """Check the shared format markers, optionally enforcing the export schema.

    Linux's existing writable repository permits operational objects such as
    failure-injection triggers. The new Windows export reader accepts only the
    two-table snapshot schema, without changing the Linux writer contract.
    """
    if (
        connection.execute("PRAGMA user_version").fetchone()[0] != 1
        or connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
        or connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete"
    ):
        raise HistoryStorageError()
    if not strict_schema:
        return
    objects = connection.execute(
        "SELECT type, name, tbl_name FROM sqlite_schema ORDER BY name"
    ).fetchall()
    if objects != [
        ("table", "jobs", "jobs"),
        ("index", "sqlite_autoindex_jobs_1", "jobs"),
        ("index", "sqlite_autoindex_symbols_1", "symbols"),
        ("table", "symbols", "symbols"),
    ]:
        raise HistoryStorageError()
    if connection.execute("PRAGMA table_info(jobs)").fetchall() != [
        (0, "job_id", "TEXT", 0, None, 1),
        (1, "job_json", "TEXT", 1, None, 0),
    ] or connection.execute("PRAGMA table_info(symbols)").fetchall() != [
        (0, "job_id", "TEXT", 1, None, 1),
        (1, "ordinal", "INTEGER", 1, None, 2),
        (2, "state_json", "TEXT", 1, None, 0),
    ]:
        raise HistoryStorageError()
    if connection.execute("PRAGMA foreign_key_list(symbols)").fetchall() != [
        (0, 0, "jobs", "job_id", "job_id", "NO ACTION", "NO ACTION", "NONE")
    ]:
        raise HistoryStorageError()


def validate_selection(codes: tuple[str, ...], all_targets: bool) -> None:
    if bool(codes) == all_targets:
        raise HistoryError(
            "TARGET_SELECTION_REQUIRED", "--code 또는 --all-targets 중 하나가 필요합니다."
        )
    if len(codes) != len(set(codes)):
        raise HistoryError("DUPLICATE_CODE", "중복 --code는 허용하지 않습니다.")


def read_selected(
    connection: sqlite3.Connection,
    job_id: str,
    *,
    codes: tuple[str, ...] = (),
    all_targets: bool = False,
) -> tuple[HistoryJob, tuple[SymbolHistory, ...]]:
    """Read in requested order; the caller owns one transaction and file guard."""
    validate_selection(codes, all_targets)
    row = connection.execute("SELECT job_json FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    if row is None:
        raise HistoryError("JOB_NOT_FOUND", "지정한 일봉 작업이 없습니다. create가 필요합니다.")
    job = HistoryJob.model_validate_json(row[0])
    if job.job_id != job_id:
        raise HistoryStorageError()
    if all_targets:
        ordinals = tuple(range(len(job.targets)))
    else:
        by_code = {target.short_code: index for index, target in enumerate(job.targets)}
        if any(code not in by_code for code in codes):
            raise HistoryError("SYMBOL_NOT_FOUND", "해당 종목은 이 작업의 고정 대상이 아닙니다.")
        ordinals = tuple(by_code[code] for code in codes)
    return job, tuple(read_symbol(connection, job, ordinal) for ordinal in ordinals)


def read_symbol(connection: sqlite3.Connection, job: HistoryJob, ordinal: int) -> SymbolHistory:
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
