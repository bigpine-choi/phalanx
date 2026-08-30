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

import pytest

from phalanx.domain import (
    AlignedPricePanel,
    AllocationBacktestConfig,
    AllocationPolicyInput,
    AllocationTarget,
)
from phalanx.portfolio.allocation_backtest import run_allocation_backtest
from phalanx.portfolio.allocation_policies import (
    EqualWeightBuyAndHold,
    WeeklyEqualWeight,
    WeeklyInverseVolatility,
)
from phalanx.portfolio.errors import (
    AllocationZeroVolatilityError,
    InsufficientAllocationObservationsError,
)


def _dates(count: int) -> tuple[date, ...]:
    first = date(2020, 1, 1)
    return tuple(first + timedelta(days=index) for index in range(count))


def _panel(
    close_prices: tuple[tuple[Decimal, ...], ...],
    *,
    open_prices: tuple[tuple[Decimal, ...], ...] | None = None,
    stock_codes: tuple[str, ...] = ("005930", "000660"),
) -> AlignedPricePanel:
    return AlignedPricePanel(
        stock_codes=stock_codes,
        dates=_dates(len(close_prices)),
        open_prices=close_prices if open_prices is None else open_prices,
        close_prices=close_prices,
    )


def _trending_panel(count: int) -> AlignedPricePanel:
    rows: list[tuple[Decimal, Decimal]] = []
    first = Decimal("100")
    second = Decimal("200")
    for index in range(count):
        if index:
            first *= Decimal("1.01") if index % 2 else Decimal("0.995")
            second *= Decimal("0.997") if index % 2 else Decimal("1.008")
        rows.append((first, second))
    return _panel(tuple(rows))


class SpyEqualWeightPolicy:
    policy_id = "spy_equal_weight"
    policy_version = "1"

    def __init__(self) -> None:
        self.inputs: list[AllocationPolicyInput] = []

    def should_rebalance(self, signal_number: int) -> bool:
        return True

    def build_target(
        self,
        policy_input: AllocationPolicyInput,
        target_equity_weight: Decimal,
    ) -> AllocationTarget:
        self.inputs.append(policy_input)
        first = target_equity_weight / Decimal(len(policy_input.stock_codes))
        leading = tuple(first for _ in policy_input.stock_codes[:-1])
        weights = (*leading, target_equity_weight - sum(leading, Decimal(0)))
        return AllocationTarget(
            signal_date=policy_input.signal_date,
            stock_codes=policy_input.stock_codes,
            target_weights=weights,
            policy_id=self.policy_id,
            target_equity_weight=target_equity_weight,
        )


def test_default_schedule_has_no_execution_before_504_returns_and_uses_next_open() -> None:
    panel = _trending_panel(506)

    result = run_allocation_backtest(panel, WeeklyEqualWeight(), AllocationBacktestConfig())

    assert len(result.rebalances) == 1
    assert result.rebalances[0].target.signal_date == panel.dates[504]
    assert result.rebalances[0].execution_date == panel.dates[505]
    assert result.dates[0] == panel.dates[505]


def test_504_training_returns_without_a_following_open_cannot_execute() -> None:
    with pytest.raises(InsufficientAllocationObservationsError, match=r"505개.*506개"):
        run_allocation_backtest(
            _trending_panel(505),
            WeeklyEqualWeight(),
            AllocationBacktestConfig(),
        )


def test_policy_receives_at_most_756_past_returns_and_never_future_observations() -> None:
    panel = _trending_panel(770)
    policy = SpyEqualWeightPolicy()

    result = run_allocation_backtest(panel, policy, AllocationBacktestConfig())

    assert len(policy.inputs[0].return_values) == 504
    assert max(len(value.return_values) for value in policy.inputs) == 756
    assert len(policy.inputs[-1].return_values) == 756
    assert len(policy.inputs) == len(result.rebalances)
    for policy_input in policy.inputs:
        assert policy_input.return_dates[-1] == policy_input.signal_date
        assert all(value <= policy_input.signal_date for value in policy_input.return_dates)
        signal_index = panel.dates.index(policy_input.signal_date)
        with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
            expected_return = tuple(
                panel.close_prices[signal_index][column]
                / panel.close_prices[signal_index - 1][column]
                - Decimal(1)
                for column in range(len(panel.stock_codes))
            )
        assert policy_input.return_values[-1] == expected_return


def test_weekly_policy_signals_and_executions_are_exactly_five_common_days_apart() -> None:
    panel = _trending_panel(521)

    result = run_allocation_backtest(panel, WeeklyEqualWeight(), AllocationBacktestConfig())

    assert tuple(record.target.signal_date for record in result.rebalances) == tuple(
        panel.dates[index] for index in (504, 509, 514, 519)
    )
    assert tuple(record.execution_date for record in result.rebalances) == tuple(
        panel.dates[index] for index in (505, 510, 515, 520)
    )


def test_signal_close_is_not_used_for_execution_when_next_open_has_a_large_gap() -> None:
    closes = tuple((Decimal("100"),) for _ in range(4))
    opens = (
        (Decimal("100"),),
        (Decimal("100"),),
        (Decimal("100"),),
        (Decimal("1000"),),
    )
    panel = _panel(closes, open_prices=opens, stock_codes=("005930",))
    config = AllocationBacktestConfig(
        minimum_training_returns=2,
        maximum_training_returns=2,
        rebalance_interval=5,
        target_equity_weight=Decimal(1),
        buy_cost_rate=Decimal(0),
        sell_cost_rate=Decimal(0),
    )

    result = run_allocation_backtest(panel, WeeklyEqualWeight(), config)

    assert result.rebalances[0].target.signal_date == panel.dates[2]
    assert result.rebalances[0].execution_date == panel.dates[3]
    assert result.net_asset_values == (Decimal("0.1"),)


def test_buy_and_hold_trades_once_and_weights_drift_while_weekly_policy_keeps_schedule() -> None:
    closes = (
        (Decimal("100"), Decimal("100")),
        (Decimal("101"), Decimal("99")),
        (Decimal("102"), Decimal("98")),
        (Decimal("100"), Decimal("100")),
        (Decimal("200"), Decimal("50")),
        (Decimal("200"), Decimal("50")),
        (Decimal("300"), Decimal("25")),
        (Decimal("300"), Decimal("25")),
    )
    panel = _panel(closes)
    config = AllocationBacktestConfig(
        minimum_training_returns=2,
        maximum_training_returns=3,
        rebalance_interval=2,
        buy_cost_rate=Decimal(0),
        sell_cost_rate=Decimal(0),
    )

    buy_and_hold = run_allocation_backtest(panel, EqualWeightBuyAndHold(), config)
    weekly = run_allocation_backtest(panel, WeeklyEqualWeight(), config)

    assert len(buy_and_hold.rebalances) == 1
    assert len(weekly.rebalances) == 3
    assert tuple(record.execution_date for record in weekly.rebalances) == tuple(
        panel.dates[index] for index in (3, 5, 7)
    )
    assert buy_and_hold.realized_weights[0] == buy_and_hold.rebalances[0].realized_weights
    assert buy_and_hold.realized_weights[-1] != buy_and_hold.rebalances[0].target.target_weights
    assert buy_and_hold.realized_weights[-1][0] > buy_and_hold.realized_weights[-1][1]


def test_asymmetric_costs_reconcile_self_financing_and_leave_nonnegative_cash() -> None:
    closes = (
        (Decimal("100"), Decimal("100")),
        (Decimal("101"), Decimal("99")),
        (Decimal("102"), Decimal("98")),
        (Decimal("100"), Decimal("100")),
        (Decimal("200"), Decimal("50")),
        (Decimal("200"), Decimal("50")),
    )
    panel = _panel(closes)
    config = AllocationBacktestConfig(
        minimum_training_returns=2,
        maximum_training_returns=3,
        rebalance_interval=2,
        target_equity_weight=Decimal("0.8"),
        buy_cost_rate=Decimal("0.01"),
        sell_cost_rate=Decimal("0.02"),
    )

    result = run_allocation_backtest(panel, WeeklyEqualWeight(), config)
    second = result.rebalances[1]
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        bought = second.buy_gross_turnover * second.pre_trade_nav
        sold = second.sell_gross_turnover * second.pre_trade_nav
        expected_cost = bought * config.buy_cost_rate + sold * config.sell_cost_rate
        expected_post_trade_nav = second.pre_trade_nav - second.transaction_cost
        expected_cash = (Decimal(1) - config.target_equity_weight) * second.post_trade_nav
        expected_cumulative_cost = sum(
            (record.transaction_cost for record in result.rebalances),
            Decimal(0),
        )

    assert bought > 0
    assert sold > 0
    assert second.transaction_cost == expected_cost
    assert second.post_trade_nav == expected_post_trade_nav
    assert second.cash_after == expected_cash
    assert second.cash_after >= 0
    assert all(value >= 0 for value in result.realized_cash_weights)
    assert result.cumulative_transaction_cost == expected_cumulative_cost


def test_all_three_policies_share_data_first_execution_and_cost_assumptions() -> None:
    panel = _trending_panel(506)
    config = AllocationBacktestConfig()

    results = (
        run_allocation_backtest(panel, WeeklyEqualWeight(), config),
        run_allocation_backtest(panel, WeeklyInverseVolatility(), config),
        run_allocation_backtest(panel, EqualWeightBuyAndHold(), config),
    )

    assert all(result.stock_codes == panel.stock_codes for result in results)
    assert all(result.dates == results[0].dates for result in results)
    assert all(result.rebalances[0].execution_date == panel.dates[505] for result in results)
    assert all(result.rebalances[0].pre_trade_nav == Decimal(1) for result in results)
    for result in results:
        first = result.rebalances[0]
        with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
            bought = first.buy_gross_turnover * first.pre_trade_nav
            sold = first.sell_gross_turnover * first.pre_trade_nav
            expected_cost = bought * config.buy_cost_rate + sold * config.sell_cost_rate
        assert first.transaction_cost == expected_cost
        assert first.target.target_equity_weight == config.target_equity_weight


def test_inverse_volatility_rejects_a_zero_sample_volatility() -> None:
    constant_panel = _panel(tuple((Decimal("100"), Decimal("200")) for _ in range(506)))

    with pytest.raises(AllocationZeroVolatilityError, match="005930"):
        run_allocation_backtest(
            constant_panel,
            WeeklyInverseVolatility(),
            AllocationBacktestConfig(),
        )


def test_max_drawdown_includes_the_initial_nav_anchor() -> None:
    closes = tuple((value,) for value in map(Decimal, ("100", "100", "100", "90")))
    opens = tuple((Decimal("100"),) for _ in closes)
    panel = _panel(closes, open_prices=opens, stock_codes=("005930",))
    config = AllocationBacktestConfig(
        minimum_training_returns=2,
        maximum_training_returns=2,
        rebalance_interval=5,
        target_equity_weight=Decimal(1),
        buy_cost_rate=Decimal(0),
        sell_cost_rate=Decimal(0),
    )

    result = run_allocation_backtest(panel, EqualWeightBuyAndHold(), config)

    assert result.net_asset_values == (Decimal("0.9"),)
    assert result.max_drawdown == Decimal("-0.1")


def test_backtest_results_do_not_depend_on_the_process_decimal_context() -> None:
    panel = _trending_panel(12)
    config = AllocationBacktestConfig(
        minimum_training_returns=3,
        maximum_training_returns=5,
        rebalance_interval=3,
    )
    original = getcontext().copy()
    try:
        getcontext().prec = 4
        getcontext().rounding = ROUND_DOWN
        low_context = run_allocation_backtest(panel, WeeklyEqualWeight(), config)
        assert getcontext().prec == 4
        assert getcontext().rounding == ROUND_DOWN

        getcontext().prec = 80
        getcontext().rounding = ROUND_UP
        high_context = run_allocation_backtest(panel, WeeklyEqualWeight(), config)
        assert getcontext().prec == 80
        assert getcontext().rounding == ROUND_UP
    finally:
        setcontext(original)

    assert low_context == high_context
