"""Package-private, provider-neutral allocation signal scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from itertools import pairwise

from phalanx.domain import (
    AlignedPricePanel,
    AlignedReturnMatrix,
    AllocationBacktestConfig,
    AllocationPolicyInput,
)
from phalanx.portfolio.errors import InsufficientAllocationObservationsError

_ALLOCATION_DECIMAL_PRECISION = 50
_ONE = Decimal(1)


@dataclass(frozen=True, slots=True)
class AllocationSignalWindow:
    """One immutable trailing-return window indexed by its return end date."""

    as_of_index: int
    policy_input: AllocationPolicyInput


def build_price_panel_signal_windows(
    panel: AlignedPricePanel,
    config: AllocationBacktestConfig,
) -> tuple[AllocationSignalWindow, ...]:
    """Build signal windows from closes while retaining a next-open execution date."""

    required_prices = config.minimum_training_returns + 2
    if len(panel.dates) < required_prices:
        raise InsufficientAllocationObservationsError(len(panel.dates), required_prices)

    matrix = build_price_panel_return_matrix(panel)
    return _build_signal_windows(
        stock_codes=matrix.stock_codes,
        return_dates=matrix.dates,
        return_values=matrix.values,
        minimum_observations=config.minimum_training_returns,
        maximum_observations=config.maximum_training_returns,
        rebalance_interval=config.rebalance_interval,
    )


def build_price_panel_return_matrix(panel: AlignedPricePanel) -> AlignedReturnMatrix:
    """Calculate the one shared close-to-close Decimal matrix from an aligned panel."""

    calculation_context = Context(
        prec=_ALLOCATION_DECIMAL_PRECISION,
        rounding=ROUND_HALF_EVEN,
    )
    with localcontext(calculation_context):
        return_values = _close_returns(panel.close_prices)
    return AlignedReturnMatrix(
        stock_codes=panel.stock_codes,
        dates=panel.dates[1:],
        values=return_values,
    )


def build_return_matrix_signal_windows(
    matrix: AlignedReturnMatrix,
    *,
    minimum_observations: int,
    maximum_observations: int,
    rebalance_interval: int,
) -> tuple[AllocationSignalWindow, ...]:
    """Build the same signal windows directly on return-date matrix indices."""

    required_returns = minimum_observations + 1
    if len(matrix.dates) < required_returns:
        raise InsufficientAllocationObservationsError(len(matrix.dates), required_returns)
    return _build_signal_windows(
        stock_codes=matrix.stock_codes,
        return_dates=matrix.dates,
        return_values=matrix.values,
        minimum_observations=minimum_observations,
        maximum_observations=maximum_observations,
        rebalance_interval=rebalance_interval,
    )


def _close_returns(
    close_prices: tuple[tuple[Decimal, ...], ...],
) -> tuple[tuple[Decimal, ...], ...]:
    return tuple(
        tuple(current / previous - _ONE for previous, current in zip(old, new, strict=True))
        for old, new in pairwise(close_prices)
    )


def _build_signal_windows(
    *,
    stock_codes: tuple[str, ...],
    return_dates: tuple[date, ...],
    return_values: tuple[tuple[Decimal, ...], ...],
    minimum_observations: int,
    maximum_observations: int,
    rebalance_interval: int,
) -> tuple[AllocationSignalWindow, ...]:
    windows: list[AllocationSignalWindow] = []
    as_of_indices = range(
        minimum_observations - 1,
        len(return_dates) - 1,
        rebalance_interval,
    )
    for signal_number, as_of_index in enumerate(as_of_indices):
        window_start = max(
            0,
            as_of_index + 1 - maximum_observations,
        )
        windows.append(
            AllocationSignalWindow(
                as_of_index=as_of_index,
                policy_input=AllocationPolicyInput(
                    signal_date=return_dates[as_of_index],
                    signal_number=signal_number,
                    stock_codes=stock_codes,
                    return_dates=return_dates[window_start : as_of_index + 1],
                    return_values=return_values[window_start : as_of_index + 1],
                ),
            )
        )
    return tuple(windows)


__all__ = [
    "AllocationSignalWindow",
    "build_price_panel_return_matrix",
    "build_price_panel_signal_windows",
    "build_return_matrix_signal_windows",
]
