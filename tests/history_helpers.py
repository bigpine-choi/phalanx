"""Synthetic source provenance and daily prices for offline history-job tests."""

from contextlib import nullcontext
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from discovery_helpers import archive, master, provider

from phalanx.discovery.repository import SqliteDiscoveryRepository
from phalanx.discovery.service import DiscoveryService
from phalanx.domain.discovery import Market
from phalanx.domain.market_data import DailyBar
from phalanx.domain.price_history import HistoryView
from phalanx.market_data.history.repository import SqliteHistoryRepository
from phalanx.market_data.history.service import HistoryService

START = date(2026, 8, 1)
END = date(2026, 8, 31)
NOW = datetime(2026, 9, 12, tzinfo=UTC)
CODES = ("005930", "0001A0")


def source(tmp_path: Path) -> SqliteDiscoveryRepository:
    repository = SqliteDiscoveryRepository(tmp_path / "discovery" / "discovery.sqlite3")
    DiscoveryService(
        repository,
        provider(
            {
                Market.KOSPI: archive(Market.KOSPI, master()),
                Market.KOSDAQ: archive(
                    Market.KOSDAQ, master(Market.KOSDAQ, {0: b"0001A0", 9: b"KR70001A0001"})
                ),
            }
        ),
    ).refresh()
    return repository


def job(tmp_path: Path) -> tuple[HistoryService, HistoryView, SqliteDiscoveryRepository]:
    discovery = source(tmp_path)
    snapshot = discovery.load().snapshot
    assert snapshot is not None
    repository = SqliteHistoryRepository(tmp_path / "history" / "history.sqlite3")
    service = HistoryService(repository, clock=lambda: NOW)
    view = service.create(discovery, snapshot.run_id, START, END, codes=CODES)
    return service, view, discovery


def bar(code: str, close: str = "110.0010") -> DailyBar:
    return DailyBar(
        stock_code=code,
        trade_date=date(2026, 8, 5),
        open_price=Decimal("100"),
        high_price=Decimal("120"),
        low_price=Decimal("90"),
        close_price=Decimal(close),
        volume=123,
    )


class Reader:
    def __init__(self, outcomes: dict[str, tuple[DailyBar, ...] | BaseException] | None = None):
        self.outcomes = outcomes or {code: (bar(code),) for code in CODES}
        self.calls: list[str] = []
        self.opened = 0

    def factory(self):
        self.opened += 1
        return nullcontext(self)

    def fetch_daily_bars(self, code: str, start: date, end: date) -> tuple[DailyBar, ...]:
        assert (start, end) == (START, END)
        self.calls.append(code)
        result = self.outcomes[code]
        if isinstance(result, BaseException):
            raise result
        return result
