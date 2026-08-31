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

import phalanx.portfolio.allocation_backtest as allocation_backtest_module
from phalanx.domain import (
    AlignedPricePanel,
    AllocationBacktestConfig,
    AllocationPolicyInput,
    AllocationTarget,
)
from phalanx.portfolio.allocation_backtest import (
    ScheduledAllocationTarget,
    annual_cash_yield_to_daily_growth_factor,
    run_allocation_backtest,
    run_allocation_backtest_with_dynamic_targets,
    run_allocation_backtest_with_targets,
)
from phalanx.portfolio.allocation_policies import (
    EqualWeightBuyAndHold,
    WeeklyEqualWeight,
    WeeklyInverseVolatility,
)
from phalanx.portfolio.errors import (
    AllocationSelfFinancingError,
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


def _scheduled_target(
    panel: AlignedPricePanel,
    execution_index: int,
    target_equity_weight: Decimal,
    *,
    policy_id: str = "dynamic_equity_target",
) -> ScheduledAllocationTarget:
    equal_weight = target_equity_weight / Decimal(len(panel.stock_codes))
    leading_weights = tuple(equal_weight for _ in panel.stock_codes[:-1])
    target_weights = (
        *leading_weights,
        target_equity_weight - sum(leading_weights, Decimal(0)),
    )
    return ScheduledAllocationTarget(
        execution_index=execution_index,
        target=AllocationTarget(
            signal_date=panel.dates[execution_index - 1],
            stock_codes=panel.stock_codes,
            target_weights=target_weights,
            policy_id=policy_id,
            target_equity_weight=target_equity_weight,
        ),
    )


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


def test_fully_invested_realized_weights_reconcile_decimal_division_residual() -> None:
    stock_values = (
        Decimal("0.92280519650127515734905819500520392970358217226354"),
        Decimal("0.07985796986761589854269450522044876830051709157211"),
    )
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        nav = sum(stock_values, Decimal(0))
        independently_divided = tuple(value / nav for value in stock_values)
        assert Decimal(1) - sum(independently_divided, Decimal(0)) == Decimal("-1E-49")

        weights, cash_weight = allocation_backtest_module._realized_weights(
            stock_values,
            Decimal(0),
            nav,
        )

        assert cash_weight == Decimal(0)
        assert all(weight >= 0 for weight in weights)
        assert sum(weights, Decimal(0)) + cash_weight == Decimal(1)


def test_fully_invested_residual_anchor_skips_a_zero_weight_last_asset() -> None:
    stock_values = (
        Decimal("0.92280519650127515734905819500520392970358217226354"),
        Decimal("0.07985796986761589854269450522044876830051709157211"),
        Decimal(0),
    )
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        nav = sum(stock_values, Decimal(0))

        weights, cash_weight = allocation_backtest_module._realized_weights(
            stock_values,
            Decimal(0),
            nav,
        )

        assert weights[-1] == Decimal(0)
        assert cash_weight == Decimal(0)
        assert all(weight >= 0 for weight in weights)
        assert sum(weights, Decimal(0)) + cash_weight == Decimal(1)


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


def test_dynamic_equity_targets_preserve_asymmetric_self_financing_costs() -> None:
    panel = _panel(
        tuple((Decimal("100"),) for _ in range(5)),
        stock_codes=("005930",),
    )
    config = AllocationBacktestConfig(
        minimum_training_returns=2,
        maximum_training_returns=2,
        rebalance_interval=2,
        target_equity_weight=Decimal("0.995"),
        buy_cost_rate=Decimal("0.01"),
        sell_cost_rate=Decimal("0.02"),
    )
    schedule = (
        _scheduled_target(panel, 1, Decimal("0.8")),
        _scheduled_target(panel, 3, Decimal("0.3")),
    )

    result = run_allocation_backtest_with_dynamic_targets(
        panel,
        "dynamic_equity_target",
        schedule,
        config,
        annual_cash_yield=Decimal(0),
    )

    first, second = result.rebalances
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        first_bought = first.buy_gross_turnover * first.pre_trade_nav
        second_sold = second.sell_gross_turnover * second.pre_trade_nav
        expected_first_cost = first_bought * config.buy_cost_rate
        expected_second_cost = second_sold * config.sell_cost_rate
        expected_cumulative_cost = first.transaction_cost + second.transaction_cost
        expected_post_trade_navs = tuple(
            record.pre_trade_nav - record.transaction_cost for record in result.rebalances
        )
        expected_cash_after = (
            Decimal("0.2") * first.post_trade_nav,
            Decimal("0.7") * second.post_trade_nav,
        )

    assert tuple(record.target.target_equity_weight for record in result.rebalances) == (
        Decimal("0.8"),
        Decimal("0.3"),
    )
    assert first_bought > 0
    assert second_sold > 0
    assert first.transaction_cost == expected_first_cost
    assert second.transaction_cost == expected_second_cost
    assert tuple(record.post_trade_nav for record in result.rebalances) == expected_post_trade_navs
    assert tuple(record.cash_after for record in result.rebalances) == expected_cash_after
    assert result.cumulative_transaction_cost == expected_cumulative_cost


def test_cash_yield_accrues_after_first_execution_before_each_later_open() -> None:
    panel = _panel(
        tuple((Decimal("100"),) for _ in range(4)),
        stock_codes=("005930",),
    )
    config = AllocationBacktestConfig(
        minimum_training_returns=1,
        maximum_training_returns=1,
        rebalance_interval=2,
        target_equity_weight=Decimal("0.9"),
        buy_cost_rate=Decimal(0),
        sell_cost_rate=Decimal(0),
        annualization_trading_days=2,
    )
    schedule = (
        _scheduled_target(panel, 1, Decimal("0.5")),
        _scheduled_target(panel, 3, Decimal("0.5")),
    )

    result = run_allocation_backtest_with_dynamic_targets(
        panel,
        "dynamic_equity_target",
        schedule,
        config,
        annual_cash_yield=Decimal("0.21"),
    )

    assert result.rebalances[0].pre_trade_nav == Decimal(1)
    assert result.rebalances[0].cash_after == Decimal("0.5")
    assert result.net_asset_values == (
        Decimal("1.0"),
        Decimal("1.050"),
        Decimal("1.10500"),
    )
    assert result.rebalances[1].pre_trade_nav == Decimal("1.10500")
    assert result.rebalances[1].cash_after == Decimal("0.552500")


def test_three_percent_annual_cash_yield_compounds_over_252_common_days() -> None:
    context = Context(prec=50, rounding=ROUND_HALF_EVEN)
    with localcontext(context):
        daily_factor = annual_cash_yield_to_daily_growth_factor(Decimal("0.03"), 252)
        compounded = context.power(daily_factor, Decimal(252))

    assert isinstance(daily_factor, Decimal)
    assert abs(compounded - Decimal("1.03")) < Decimal("1e-46")


def test_zero_annual_cash_yield_has_exact_unit_daily_growth() -> None:
    assert annual_cash_yield_to_daily_growth_factor(Decimal(0), 252) == Decimal(1)


@pytest.mark.parametrize("annualization_trading_days", [0, -1, 252.0, True])
def test_annual_cash_yield_requires_positive_integer_trading_days(
    annualization_trading_days: object,
) -> None:
    with pytest.raises(AllocationSelfFinancingError, match=r"연환산 거래일.*양의 정수"):
        annual_cash_yield_to_daily_growth_factor(
            Decimal("0.03"),
            annualization_trading_days,  # type: ignore[arg-type]
        )


def test_dynamic_target_uses_next_open_and_does_not_accrue_unknown_pre_execution_cash() -> None:
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
        buy_cost_rate=Decimal(0),
        sell_cost_rate=Decimal(0),
    )
    schedule = (_scheduled_target(panel, 3, Decimal("0.5")),)

    result = run_allocation_backtest_with_dynamic_targets(
        panel,
        "dynamic_equity_target",
        schedule,
        config,
        annual_cash_yield=Decimal("0.03"),
    )

    assert result.rebalances[0].target.signal_date == panel.dates[2]
    assert result.rebalances[0].execution_date == panel.dates[3]
    assert result.rebalances[0].pre_trade_nav == Decimal(1)
    assert result.net_asset_values == (Decimal("0.55"),)


def test_zero_cash_yield_is_exactly_the_existing_static_target_result() -> None:
    panel = _panel(
        (
            (Decimal("100"), Decimal("100")),
            (Decimal("101"), Decimal("99")),
            (Decimal("102"), Decimal("98")),
            (Decimal("100"), Decimal("100")),
            (Decimal("200"), Decimal("50")),
            (Decimal("200"), Decimal("50")),
        )
    )
    config = AllocationBacktestConfig(
        minimum_training_returns=2,
        maximum_training_returns=3,
        rebalance_interval=2,
        target_equity_weight=Decimal("0.8"),
        buy_cost_rate=Decimal("0.01"),
        sell_cost_rate=Decimal("0.02"),
    )
    schedule = (
        _scheduled_target(
            panel,
            3,
            config.target_equity_weight,
            policy_id="static_target",
        ),
        _scheduled_target(
            panel,
            5,
            config.target_equity_weight,
            policy_id="static_target",
        ),
    )

    existing = run_allocation_backtest_with_targets(
        panel,
        "static_target",
        schedule,
        config,
    )
    additive = run_allocation_backtest_with_dynamic_targets(
        panel,
        "static_target",
        schedule,
        config,
        annual_cash_yield=Decimal(0),
    )

    assert additive == existing


@pytest.mark.parametrize(
    "annual_cash_yield",
    [Decimal("-1"), Decimal("-1.01"), Decimal("NaN"), Decimal("Infinity"), 0.03],
)
def test_dynamic_target_rejects_invalid_annual_cash_yield(annual_cash_yield: object) -> None:
    panel = _panel(
        tuple((Decimal("100"),) for _ in range(3)),
        stock_codes=("005930",),
    )
    schedule = (_scheduled_target(panel, 1, Decimal("0.5")),)

    with pytest.raises(AllocationSelfFinancingError, match=r"-1보다 큰.*Decimal"):
        run_allocation_backtest_with_dynamic_targets(
            panel,
            "dynamic_equity_target",
            schedule,
            AllocationBacktestConfig(),
            annual_cash_yield=annual_cash_yield,  # type: ignore[arg-type]
        )


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
