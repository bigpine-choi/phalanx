"""Application service for direct and active-universe daily market data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from phalanx.domain import DailyBar, KoreanStock
from phalanx.market_data.errors import (
    UniverseReaderRequiredError,
    UniverseStockMarketDataError,
)
from phalanx.market_data.validation import validate_daily_date_range


class DailyBarReader(Protocol):
    def fetch_daily_bars(
        self,
        stock_code: str,
        start: date,
        end: date,
    ) -> tuple[DailyBar, ...]: ...


class UniverseReader(Protocol):
    def list_stocks(self) -> tuple[KoreanStock, ...]: ...


@dataclass(frozen=True, slots=True)
class StockDailyBars:
    """One active universe stock and its complete immutable daily history."""

    stock: KoreanStock
    bars: tuple[DailyBar, ...]


class MarketDataService:
    """Coordinate market-data reads without persistence or portfolio decisions."""

    def __init__(
        self,
        daily_bar_reader: DailyBarReader,
        universe_reader: UniverseReader | None = None,
    ) -> None:
        self._daily_bar_reader = daily_bar_reader
        self._universe_reader = universe_reader

    def fetch_daily_bars(
        self,
        stock_code: str,
        start: date,
        end: date,
    ) -> tuple[DailyBar, ...]:
        """Fetch one stock through the provider-neutral service boundary."""

        return self._daily_bar_reader.fetch_daily_bars(stock_code, start, end)

    def fetch_active_universe(
        self,
        start: date,
        end: date,
    ) -> tuple[StockDailyBars, ...]:
        """Sequentially fetch every enabled stock and never hide a stock failure."""

        validated_start, validated_end = validate_daily_date_range(start, end)
        if self._universe_reader is None:
            raise UniverseReaderRequiredError("활성 유니버스 조회기가 구성되지 않았습니다.")

        results: list[StockDailyBars] = []
        for stock in self._universe_reader.list_stocks():
            if not stock.enabled:
                continue
            try:
                bars = self._daily_bar_reader.fetch_daily_bars(
                    stock.stock_code,
                    validated_start,
                    validated_end,
                )
            except Exception as error:
                raise UniverseStockMarketDataError(
                    stock.stock_code,
                    stock.stock_name,
                ) from error
            results.append(StockDailyBars(stock=stock, bars=bars))
        return tuple(results)


__all__ = [
    "DailyBarReader",
    "MarketDataService",
    "StockDailyBars",
    "UniverseReader",
]
