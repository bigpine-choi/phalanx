from __future__ import annotations

from datetime import date, timedelta
from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    ROUND_UP,
    Context,
    Decimal,
    getcontext,
    localcontext,
    setcontext,
)

from phalanx.domain import AlignedPricePanel, AlignedReturnMatrix, AllocationBacktestConfig
from phalanx.portfolio._allocation_schedule import (
    build_price_panel_signal_windows,
    build_return_matrix_signal_windows,
)


def _trending_panel(count: int) -> AlignedPricePanel:
    dates = tuple(date(2020, 1, 1) + timedelta(days=index) for index in range(count))
    rows: list[tuple[Decimal, Decimal]] = []
    first = Decimal("100")
    second = Decimal("200")
    for index in range(count):
        if index:
            first *= Decimal("1.01") if index % 2 else Decimal("0.995")
            second *= Decimal("0.997") if index % 2 else Decimal("1.008")
        rows.append((first, second))
    prices = tuple(rows)
    return AlignedPricePanel(
        stock_codes=("005930", "000660"),
        dates=dates,
        open_prices=prices,
        close_prices=prices,
    )


def _return_matrix(panel: AlignedPricePanel) -> AlignedReturnMatrix:
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        values = tuple(
            tuple(
                current / previous - Decimal(1) for previous, current in zip(old, new, strict=True)
            )
            for old, new in zip(
                panel.close_prices,
                panel.close_prices[1:],
                strict=False,
            )
        )
    return AlignedReturnMatrix(
        stock_codes=panel.stock_codes,
        dates=panel.dates[1:],
        values=values,
    )


def _matrix_windows(matrix: AlignedReturnMatrix, config: AllocationBacktestConfig):
    return build_return_matrix_signal_windows(
        matrix,
        minimum_observations=config.minimum_training_returns,
        maximum_observations=config.maximum_training_returns,
        rebalance_interval=config.rebalance_interval,
    )


def test_price_and_return_schedules_preserve_default_504_756_5_contract() -> None:
    panel = _trending_panel(770)
    matrix = _return_matrix(panel)
    config = AllocationBacktestConfig()

    price_windows = build_price_panel_signal_windows(panel, config)
    return_windows = _matrix_windows(matrix, config)

    assert return_windows == price_windows
    assert tuple(window.as_of_index for window in return_windows[:4]) == (503, 508, 513, 518)
    assert tuple(window.policy_input.signal_number for window in return_windows[:4]) == (
        0,
        1,
        2,
        3,
    )
    assert return_windows[0].policy_input.signal_date == matrix.dates[503]
    assert len(return_windows[0].policy_input.return_values) == 504
    assert max(len(window.policy_input.return_values) for window in return_windows) == 756
    assert len(return_windows[-1].policy_input.return_values) == 756
    for window in return_windows:
        policy_input = window.policy_input
        assert policy_input.return_dates[-1] == matrix.dates[window.as_of_index]
        assert policy_input.return_dates[-1] == policy_input.signal_date
        assert len(policy_input.return_dates) == len(policy_input.return_values)
        assert len(policy_input.return_values) <= 756


def test_return_schedule_does_not_expose_observations_after_each_as_of_date() -> None:
    matrix = _return_matrix(_trending_panel(511))
    changed_values = (
        *matrix.values[:504],
        *((Decimal("0.5"), Decimal("-0.5")) for _ in matrix.values[504:]),
    )
    changed = AlignedReturnMatrix(
        stock_codes=matrix.stock_codes,
        dates=matrix.dates,
        values=changed_values,
    )

    original_windows = _matrix_windows(matrix, AllocationBacktestConfig())
    changed_windows = _matrix_windows(changed, AllocationBacktestConfig())

    assert original_windows[0] == changed_windows[0]
    assert original_windows[1] != changed_windows[1]
    assert original_windows[0].as_of_index == 503
    assert all(
        return_date <= original_windows[0].policy_input.signal_date
        for return_date in original_windows[0].policy_input.return_dates
    )


def test_price_schedule_is_independent_of_the_process_decimal_context() -> None:
    panel = _trending_panel(511)
    config = AllocationBacktestConfig()
    original = getcontext().copy()
    try:
        getcontext().prec = 4
        getcontext().rounding = ROUND_DOWN
        low_context = build_price_panel_signal_windows(panel, config)
        assert getcontext().prec == 4
        assert getcontext().rounding == ROUND_DOWN

        getcontext().prec = 80
        getcontext().rounding = ROUND_UP
        high_context = build_price_panel_signal_windows(panel, config)
        assert getcontext().prec == 80
        assert getcontext().rounding == ROUND_UP
    finally:
        setcontext(original)

    assert low_context == high_context
