"""Small domain-valid history fixtures with no platform repository imports."""

import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from phalanx.domain.discovery import Market
from phalanx.domain.market_data import DailyBar
from phalanx.domain.price_history import (
    HistoryJob,
    HistoryResult,
    HistoryTarget,
    HistoryView,
    SymbolHistory,
    SymbolStatus,
    price_data_hash,
)
from phalanx.market_data.history.reader import APPLICATION_ID, SCHEMA

CODES = ("005930", "000660", "000001")
JOB_ID = "a" * 32


def history_view() -> HistoryView:
    now = datetime(2026, 9, 26, tzinfo=UTC)
    day = date(2026, 8, 20)
    job = HistoryJob(
        job_id=JOB_ID,
        created_at=now,
        discovery_run_id="synthetic-desktop-history",
        discovery_started_at=now,
        discovery_completed_at=now,
        start=day,
        end=day,
        targets=tuple(
            HistoryTarget(
                market=Market.KOSPI,
                short_code=code,
                standard_code=None,
                name=f"합성 종목 {code}",
                policy_version="synthetic-v1",
                source_files=(),
            )
            for code in CODES
        ),
    )
    symbols = []
    for ordinal, code in enumerate(CODES):
        bar = DailyBar(
            stock_code=code,
            trade_date=day,
            open_price=Decimal("100"),
            high_price=Decimal("120"),
            low_price=Decimal("90"),
            close_price=Decimal("110.0010"),
            volume=123,
        )
        symbols.append(
            SymbolHistory(
                ordinal=ordinal,
                status=SymbolStatus.COMPLETED,
                result=HistoryResult(
                    bars=(bar,),
                    row_count=1,
                    first_trade_date=day,
                    last_trade_date=day,
                    sha256=price_data_hash((bar,)),
                ),
            )
        )
    return HistoryView(job=job, symbols=tuple(symbols))


def create_history_db(path: Path) -> HistoryView:
    path.parent.mkdir(parents=True, exist_ok=True)
    view = history_view()
    with closing(sqlite3.connect(path)) as connection, connection:
        for statement in SCHEMA:
            connection.execute(statement)
        connection.execute("PRAGMA user_version = 1")
        connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        connection.execute("INSERT INTO jobs VALUES (?, ?)", (JOB_ID, view.job.model_dump_json()))
        connection.executemany(
            "INSERT INTO symbols VALUES (?, ?, ?)",
            [(JOB_ID, s.ordinal, s.model_dump_json()) for s in view.symbols],
        )
    return view
