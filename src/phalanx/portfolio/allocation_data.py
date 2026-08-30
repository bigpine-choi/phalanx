"""Pure construction of common-date adjusted open and close price panels."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from phalanx.domain import AlignedPricePanel
from phalanx.market_data.service import StockDailyBars
from phalanx.portfolio.errors import (
    AllocationStockCodeMismatchError,
    DuplicateAllocationBarDateError,
    DuplicateAllocationStockCodeError,
    EmptyAllocationStockHistoryError,
    EmptyAllocationUniverseError,
    InsufficientAllocationObservationsError,
    InvalidAlignedPricePanelError,
    UnsortedAllocationBarsError,
)


def build_aligned_price_panel(
    histories: Sequence[StockDailyBars],
    *,
    minimum_common_observations: int = 2,
) -> AlignedPricePanel:
    """Align adjusted opens and closes on every stock's common trading dates."""

    if type(minimum_common_observations) is not int or minimum_common_observations < 2:
        raise InvalidAlignedPricePanelError("최소 공통 가격 관측치는 2 이상의 정수여야 합니다.")
    if not histories:
        raise EmptyAllocationUniverseError("활성 투자 후보 유니버스가 비어 있습니다.")

    stock_codes: list[str] = []
    prices_by_stock: list[dict[date, tuple[Decimal, Decimal]]] = []
    seen_stock_codes: set[str] = set()
    for history in histories:
        stock_code = history.stock.stock_code
        if stock_code in seen_stock_codes:
            raise DuplicateAllocationStockCodeError(stock_code)
        seen_stock_codes.add(stock_code)
        stock_codes.append(stock_code)
        prices_by_stock.append(_validated_prices(history))

    common_dates = set(prices_by_stock[0])
    for prices in prices_by_stock[1:]:
        common_dates.intersection_update(prices)
    sorted_common_dates = tuple(sorted(common_dates))
    if len(sorted_common_dates) < minimum_common_observations:
        raise InsufficientAllocationObservationsError(
            len(sorted_common_dates),
            minimum_common_observations,
        )

    return AlignedPricePanel(
        stock_codes=tuple(stock_codes),
        dates=sorted_common_dates,
        open_prices=tuple(
            tuple(prices[trade_date][0] for prices in prices_by_stock)
            for trade_date in sorted_common_dates
        ),
        close_prices=tuple(
            tuple(prices[trade_date][1] for prices in prices_by_stock)
            for trade_date in sorted_common_dates
        ),
    )


def _validated_prices(
    history: StockDailyBars,
) -> dict[date, tuple[Decimal, Decimal]]:
    stock_code = history.stock.stock_code
    if not history.bars:
        raise EmptyAllocationStockHistoryError(stock_code)

    prices: dict[date, tuple[Decimal, Decimal]] = {}
    previous_date: date | None = None
    for bar in history.bars:
        if bar.stock_code != stock_code:
            raise AllocationStockCodeMismatchError(stock_code, bar.stock_code)
        if bar.trade_date in prices:
            raise DuplicateAllocationBarDateError(stock_code)
        if previous_date is not None and bar.trade_date <= previous_date:
            raise UnsortedAllocationBarsError(stock_code)
        prices[bar.trade_date] = (bar.open_price, bar.close_price)
        previous_date = bar.trade_date
    return prices


__all__ = ["build_aligned_price_panel"]
