from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from phalanx.domain import DailyBar, KoreanStock, StockMarket
from phalanx.market_data.errors import (
    InvalidMarketDataRangeError,
    UniverseReaderRequiredError,
    UniverseStockMarketDataError,
)
from phalanx.market_data.service import MarketDataService

START = date(2026, 8, 1)
END = date(2026, 8, 31)


def _bar(stock_code: str, trade_date: date) -> DailyBar:
    return DailyBar(
        stock_code=stock_code,
        trade_date=trade_date,
        open_price=Decimal("100"),
        high_price=Decimal("120"),
        low_price=Decimal("90"),
        close_price=Decimal("110"),
        volume=1000,
    )


def _stock(
    stock_code: str,
    stock_name: str,
    market: StockMarket,
    *,
    enabled: bool = True,
) -> KoreanStock:
    return KoreanStock(
        stock_code=stock_code,
        stock_name=stock_name,
        market=market,
        enabled=enabled,
    )


class FakeDailyBarReader:
    def __init__(
        self,
        results: dict[str, tuple[DailyBar, ...] | Exception],
    ) -> None:
        self.results = results
        self.calls: list[tuple[str, date, date]] = []

    def fetch_daily_bars(
        self,
        stock_code: str,
        start: date,
        end: date,
    ) -> tuple[DailyBar, ...]:
        self.calls.append((stock_code, start, end))
        result = self.results[stock_code]
        if isinstance(result, Exception):
            raise result
        return result


class FakeUniverseReader:
    def __init__(self, stocks: tuple[KoreanStock, ...]) -> None:
        self.stocks = stocks
        self.calls = 0

    def list_stocks(self) -> tuple[KoreanStock, ...]:
        self.calls += 1
        return self.stocks


def test_service_fetches_only_active_stocks_sequentially_in_universe_order() -> None:
    first = _stock("005930", "삼성전자", StockMarket.KOSPI)
    disabled = _stock("035720", "카카오", StockMarket.KOSPI, enabled=False)
    third = _stock("035900", "JYP Ent.", StockMarket.KOSDAQ)
    reader = FakeDailyBarReader(
        {
            "005930": (_bar("005930", date(2026, 8, 3)),),
            "035900": (),
        }
    )
    universe = FakeUniverseReader((first, disabled, third))

    results = MarketDataService(reader, universe).fetch_active_universe(START, END)

    assert [result.stock for result in results] == [first, third]
    assert results[0].bars[0].stock_code == "005930"
    assert results[1].bars == ()
    assert reader.calls == [
        ("005930", START, END),
        ("035900", START, END),
    ]
    assert universe.calls == 1


def test_service_returns_empty_result_when_no_stock_is_active() -> None:
    reader = FakeDailyBarReader({})
    universe = FakeUniverseReader((_stock("005930", "삼성전자", StockMarket.KOSPI, enabled=False),))

    assert MarketDataService(reader, universe).fetch_active_universe(START, END) == ()
    assert reader.calls == []


def test_service_reports_failing_stock_and_stops_without_silent_omission() -> None:
    first = _stock("005930", "삼성전자", StockMarket.KOSPI)
    failing = _stock("035900", "JYP Ent.", StockMarket.KOSDAQ)
    unvisited = _stock("000660", "SK하이닉스", StockMarket.KOSPI)
    cause = RuntimeError("synthetic provider failure")
    reader = FakeDailyBarReader(
        {
            "005930": (_bar("005930", START),),
            "035900": cause,
            "000660": (_bar("000660", START),),
        }
    )

    with pytest.raises(UniverseStockMarketDataError) as captured:
        MarketDataService(
            reader,
            FakeUniverseReader((first, failing, unvisited)),
        ).fetch_active_universe(START, END)

    assert captured.value.stock_code == "035900"
    assert captured.value.stock_name == "JYP Ent."
    assert "035900" in str(captured.value)
    assert "JYP Ent." in str(captured.value)
    assert captured.value.__cause__ is cause
    assert [call[0] for call in reader.calls] == ["005930", "035900"]


def test_service_validates_range_before_reading_universe_or_market_data() -> None:
    reader = FakeDailyBarReader({})
    universe = FakeUniverseReader(())

    with pytest.raises(InvalidMarketDataRangeError):
        MarketDataService(reader, universe).fetch_active_universe(END, START)

    assert universe.calls == 0
    assert reader.calls == []


def test_service_requires_a_universe_reader_for_universe_workflow() -> None:
    with pytest.raises(UniverseReaderRequiredError):
        MarketDataService(FakeDailyBarReader({})).fetch_active_universe(START, END)


def test_single_stock_service_boundary_delegates_without_persistence() -> None:
    expected = (_bar("005930", date(2026, 8, 3)),)
    reader = FakeDailyBarReader({"005930": expected})

    actual = MarketDataService(reader).fetch_daily_bars("005930", START, END)

    assert actual is expected
    assert reader.calls == [("005930", START, END)]
