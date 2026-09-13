"""Synthetic independent close histories for offline feature tests."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from phalanx.domain.discovery import Market
from phalanx.domain.market_data import DailyBar
from phalanx.domain.price_history import (
    HistoryAttempt,
    HistoryJob,
    HistoryResult,
    HistoryTarget,
    HistoryView,
    SymbolHistory,
    SymbolStatus,
    price_data_hash,
)

START = date(2025, 1, 1)
END = date(2026, 8, 31)
NOW = datetime(2026, 9, 13, tzinfo=UTC)
CODES = ("005930", "0001A0")


def bars(
    code: str,
    closes: list[str],
    *,
    start: date = START,
    step: int = 1,
) -> tuple[DailyBar, ...]:
    return tuple(
        DailyBar(
            stock_code=code,
            trade_date=start + timedelta(days=index * step),
            open_price=Decimal(close),
            high_price=Decimal(close),
            low_price=Decimal(close),
            close_price=Decimal(close),
            volume=100,
        )
        for index, close in enumerate(closes)
    )


def history(
    series: tuple[tuple[DailyBar, ...] | SymbolStatus, ...],
    *,
    codes: tuple[str, ...] = CODES,
) -> HistoryView:
    states: list[SymbolHistory] = []
    for ordinal, item in enumerate(series):
        if isinstance(item, SymbolStatus):
            states.append(
                SymbolHistory(
                    ordinal=ordinal,
                    status=item,
                    attempts=(HistoryAttempt(number=1, started_at=NOW, outcome="in_progress"),)
                    if item == SymbolStatus.IN_PROGRESS
                    else (),
                    error_code="SOURCE_TEST_ERROR" if item == SymbolStatus.FAILED else None,
                    error_message="synthetic source failure"
                    if item == SymbolStatus.FAILED
                    else None,
                )
            )
        else:
            states.append(
                SymbolHistory(
                    ordinal=ordinal,
                    status=SymbolStatus.COMPLETED if item else SymbolStatus.EMPTY,
                    result=HistoryResult(
                        bars=item,
                        row_count=len(item),
                        first_trade_date=item[0].trade_date if item else None,
                        last_trade_date=item[-1].trade_date if item else None,
                        sha256=price_data_hash(item),
                    ),
                )
            )
    return HistoryView(
        job=HistoryJob(
            job_id="a" * 32,
            created_at=NOW,
            discovery_run_id="synthetic-discovery-run",
            discovery_started_at=NOW,
            discovery_completed_at=NOW,
            start=START,
            end=END,
            targets=tuple(
                HistoryTarget(
                    market=Market.KOSPI,
                    short_code=code,
                    standard_code=f"synthetic-standard-{index}",
                    name=f"synthetic name {index}",
                    policy_version="synthetic-policy",
                    source_files=(),
                )
                for index, code in enumerate(codes)
            ),
        ),
        symbols=tuple(states),
    )
