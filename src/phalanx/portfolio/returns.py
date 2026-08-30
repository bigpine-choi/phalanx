"""Pure Decimal calculation of close-date-aligned simple returns."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from itertools import pairwise

from phalanx.domain import AlignedReturnMatrix
from phalanx.market_data.service import StockDailyBars
from phalanx.portfolio.errors import (
    DuplicateDailyBarDateError,
    DuplicateReturnStockCodeError,
    EmptyReturnUniverseError,
    EmptyStockHistoryError,
    InsufficientCommonObservationsError,
    InsufficientStockObservationsError,
    InvalidMinimumObservationsError,
    ReturnStockCodeMismatchError,
    UnsortedDailyBarsError,
)

_RETURN_DECIMAL_PRECISION = 50


def build_aligned_return_matrix(
    histories: Sequence[StockDailyBars],
    *,
    minimum_common_observations: int = 2,
) -> AlignedReturnMatrix:
    """Build oldest-first simple returns over every stock's common close dates."""

    _validate_minimum_observations(minimum_common_observations)
    if not histories:
        raise EmptyReturnUniverseError("활성 투자 후보 유니버스가 비어 있습니다.")

    stock_codes: list[str] = []
    closes_by_stock: list[dict[date, Decimal]] = []
    seen_stock_codes: set[str] = set()
    for history in histories:
        stock_code = history.stock.stock_code
        if stock_code in seen_stock_codes:
            raise DuplicateReturnStockCodeError(stock_code)
        seen_stock_codes.add(stock_code)
        stock_codes.append(stock_code)
        closes_by_stock.append(
            _validated_closes(
                history,
                minimum_observations=minimum_common_observations,
            )
        )

    common_dates = set(closes_by_stock[0])
    for closes in closes_by_stock[1:]:
        common_dates.intersection_update(closes)
    sorted_common_dates = tuple(sorted(common_dates))
    if len(sorted_common_dates) < minimum_common_observations:
        raise InsufficientCommonObservationsError(
            len(sorted_common_dates),
            minimum_common_observations,
        )

    return_context = Context(
        prec=_RETURN_DECIMAL_PRECISION,
        rounding=ROUND_HALF_EVEN,
    )
    with localcontext(return_context):
        values = tuple(
            tuple(
                closes[current_date] / closes[previous_date] - Decimal(1)
                for closes in closes_by_stock
            )
            for previous_date, current_date in pairwise(sorted_common_dates)
        )

    return AlignedReturnMatrix(
        stock_codes=tuple(stock_codes),
        dates=sorted_common_dates[1:],
        values=values,
    )


def _validated_closes(
    history: StockDailyBars,
    *,
    minimum_observations: int,
) -> dict[date, Decimal]:
    stock_code = history.stock.stock_code
    if not history.bars:
        raise EmptyStockHistoryError(stock_code)
    if len(history.bars) < minimum_observations:
        raise InsufficientStockObservationsError(
            stock_code,
            len(history.bars),
            minimum_observations,
        )

    closes: dict[date, Decimal] = {}
    previous_date: date | None = None
    for bar in history.bars:
        if bar.stock_code != stock_code:
            raise ReturnStockCodeMismatchError(stock_code, bar.stock_code)
        if bar.trade_date in closes:
            raise DuplicateDailyBarDateError(stock_code)
        if previous_date is not None and bar.trade_date < previous_date:
            raise UnsortedDailyBarsError(stock_code)
        closes[bar.trade_date] = bar.close_price
        previous_date = bar.trade_date
    return closes


def _validate_minimum_observations(value: object) -> None:
    if type(value) is not int or value < 2:
        raise InvalidMinimumObservationsError("최소 공통 종가 관측치는 2 이상의 정수여야 합니다.")


__all__ = ["build_aligned_return_matrix"]
