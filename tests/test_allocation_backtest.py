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
    calculate_volatility_scalar,
    scale_risky_sleeve,
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


_RECONCILIATION_STOCK_CODES = (
    "000660",
    "257720",
    "014680",
    "071970",
    "013030",
    "192080",
    "271560",
    "105560",
    "035420",
    "000270",
)
_RECONCILIATION_DATES = (
    date(2026, 3, 27),
    date(2026, 3, 30),
    date(2026, 3, 31),
)
_RECONCILIATION_CASH_BEFORE = Decimal(
    "1.0533901355293224561374265368887003207152558580785"
)
_RECONCILIATION_CURRENT_VALUES = tuple(
    map(
        Decimal,
        (
            "0.042170637859817921821859765169790267376835797751629",
            "0.072822738708863576114234651087489367510471215252634",
            "0.066962005711076712413426021569269381373763663692592",
            "0.060585529568117823254829857231452738939175531919019",
            "0.069614453082734991764327134109683668124453729703563",
            "0.11709143996620280351456941818152166817692364857267",
            "0.13433467788774044933763630762857231024166224155133",
            "0.082851299003142305177239190795582018928693355486753",
            "0.086291458835808546891385276974155832599816292916930",
            "0.063733182984901262811378324359555363445447263262483",
        ),
    )
)
_RECONCILIATION_PRE_TRADE_QUANTITIES = tuple(
    map(
        Decimal,
        (
            "5.1616447808834665632631291517491147340068295901627E-8",
            "0.0000019602352276948472709080659781289197176439088897075",
            "2.6004662412068626179971270512337623834471325705861E-7",
            "8.6058990863803726214246956294677185993147062384970E-7",
            "0.0000019582124636493668569430980058982747714332976006628",
            "0.0000023750799181785558522225034113898918494304999710481",
            "0.0000010868501447228191693983520034674135132820569704800",
            "5.7575607368410219025183593325630311972684750164526E-7",
            "4.2613066091757307106856926900817695111020391563916E-7",
            "4.3923627143281366513699741116164964469639740360085E-7",
        ),
    )
)
_RECONCILIATION_FAILURE_OPENS = tuple(
    map(
        Decimal,
        (
            "817000",
            "37150",
            "257500",
            "70400",
            "35550",
            "49300",
            "123600",
            "143900",
            "202500",
            "145100",
        ),
    )
)
_RECONCILIATION_RISKY_WEIGHTS = tuple(
    map(
        Decimal,
        (
            "0.059386736727",
            "0.088930896685",
            "0.087839936046",
            "0.075925264425",
            "0.0878601922",
            "0.146023341739",
            "0.155134855187",
            "0.101126882879",
            "0.109478459817",
            "0.088293434295",
        ),
    )
)
_RECONCILIATION_FORECAST = Decimal("0.32699485803561146")


def _run_reconciliation_regression(
    target_annual_volatility: Decimal,
    *,
    buy_cost_rate: Decimal = Decimal("0.001"),
    sell_cost_rate: Decimal = Decimal("0.0025"),
):
    calculation_context = Context(prec=50, rounding=ROUND_HALF_EVEN)
    with localcontext(calculation_context):
        setup_post_trade_nav = Decimal(2) * _RECONCILIATION_CASH_BEFORE
        setup_asset_value = Decimal("0.05") * setup_post_trade_nav
        initial_nav = (
            setup_post_trade_nav
            + _RECONCILIATION_CASH_BEFORE * buy_cost_rate
        )
    with localcontext(Context(prec=100, rounding=ROUND_HALF_EVEN)):
        setup_opens = tuple(
            setup_asset_value / quantity
            for quantity in _RECONCILIATION_PRE_TRADE_QUANTITIES
        )
        scalar = calculate_volatility_scalar(
            target_annual_volatility,
            _RECONCILIATION_FORECAST,
        )
        target_weights = scale_risky_sleeve(
            _RECONCILIATION_RISKY_WEIGHTS,
            scalar,
        )
        setup_target = AllocationTarget(
            signal_date=_RECONCILIATION_DATES[0],
            stock_codes=_RECONCILIATION_STOCK_CODES,
            target_weights=(Decimal("0.05"),) * 10,
            policy_id="volatility_overlay_fast_iewma",
            target_equity_weight=Decimal("0.5"),
        )
        regression_target = AllocationTarget(
            signal_date=_RECONCILIATION_DATES[1],
            stock_codes=_RECONCILIATION_STOCK_CODES,
            target_weights=target_weights,
            policy_id="volatility_overlay_fast_iewma",
            target_equity_weight=scalar,
        )
    panel = AlignedPricePanel(
        stock_codes=_RECONCILIATION_STOCK_CODES,
        dates=_RECONCILIATION_DATES,
        open_prices=(
            setup_opens,
            setup_opens,
            _RECONCILIATION_FAILURE_OPENS,
        ),
        close_prices=(
            setup_opens,
            setup_opens,
            _RECONCILIATION_FAILURE_OPENS,
        ),
    )
    config = AllocationBacktestConfig(
        minimum_training_returns=1,
        maximum_training_returns=1,
        rebalance_interval=1,
        target_equity_weight=Decimal(1),
        buy_cost_rate=buy_cost_rate,
        sell_cost_rate=sell_cost_rate,
    )
    result = run_allocation_backtest_with_dynamic_targets(
        panel,
        "volatility_overlay_fast_iewma",
        (
            ScheduledAllocationTarget(1, setup_target),
            ScheduledAllocationTarget(2, regression_target),
        ),
        config,
        annual_cash_yield=Decimal(0),
        initial_nav=initial_nav,
    )
    return result, panel, scalar


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
            nav,
            Decimal(0),
            nav,
            getcontext(),
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
            nav,
            Decimal(0),
            nav,
            getcontext(),
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


def test_fast_iewma_15_percent_decimal_ulp_reconciles_through_public_dynamic_path() -> None:
    result, panel, scalar = _run_reconciliation_regression(Decimal("0.15"))
    second = result.rebalances[1]

    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)) as context:
        desired_values = allocation_backtest_module._desired_values(
            second.target,
            second.post_trade_nav,
        )
        quantities = tuple(
            value / price
            for value, price in zip(desired_values, panel.open_prices[2], strict=True)
        )
        actual_values = tuple(
            quantity * price
            for quantity, price in zip(quantities, panel.open_prices[2], strict=True)
        )
        actual_stock_total = sum(actual_values, Decimal(0))
        pre_trade_values = tuple(
            quantity * price
            for quantity, price in zip(
                _RECONCILIATION_PRE_TRADE_QUANTITIES,
                panel.open_prices[2],
                strict=True,
            )
        )
        recombined_nav = actual_stock_total + second.cash_after
        nav_ulp = context.next_plus(second.post_trade_nav) - second.post_trade_nav
        expected_post_trade_nav = second.pre_trade_nav - second.transaction_cost
        expected_cash_after = second.post_trade_nav - actual_stock_total
        exact_weight_total = (
            sum(second.realized_weights, Decimal(0)) + second.realized_cash_weight
        )

    assert second.target.signal_date == date(2026, 3, 30)
    assert second.execution_date == date(2026, 3, 31)
    assert scalar == Decimal(
        "0.45872280959128785754530805531058095109443420937016"
    )
    assert second.pre_trade_nav == Decimal(
        "1.8498475591377288492383124839957729374324985981881"
    )
    assert pre_trade_values == _RECONCILIATION_CURRENT_VALUES
    assert second.post_trade_nav == Decimal(
        "1.8497860390784402358439935678962036831930951327833"
    )
    assert second.transaction_cost == Decimal(
        "0.000061520059288613394318916099569254239403465404831778"
    )
    assert second.cash_after == Decimal(
        "1.0012469900896383355551019429876288213394645397066"
    )
    assert second.post_trade_nav == expected_post_trade_nav
    assert second.cash_after == expected_cash_after
    assert recombined_nav - second.post_trade_nav == nav_ulp == Decimal("1E-49")
    assert second.cash_after >= 0
    assert second.buy_gross_turnover > 0
    assert second.sell_gross_turnover > 0
    assert exact_weight_total == Decimal(1)


@pytest.mark.parametrize(
    ("target_volatility", "expected_scalar", "expected_post_nav", "expected_cost", "expected_cash"),
    (
        (
            Decimal("0.20"),
            Decimal("0.61163041278838381006041074041410793479257894582688"),
            Decimal("1.8495127982850647626305315044937983148660828335524"),
            Decimal("0.00033476085266408660778097950197462256641576463569495"),
            Decimal("0.7182945220125717617486660554121031317330754577478"),
        ),
        (
            Decimal("0.25"),
            Decimal("0.76453801598547976257551342551763491849072368228360"),
            Decimal("1.8492302097656626033813970922512979002085483511462"),
            Decimal("0.00061734937206624585691539174447503722395024704188573"),
            Decimal("0.4354234140910103533651194006691880595410585691509"),
        ),
        (
            Decimal("0.30"),
            Decimal("0.91744561918257571509061611062116190218886841874033"),
            Decimal("1.8489477075869139753930812775281965192768891940856"),
            Decimal("0.00089985155081487384523120646757641815560940410253460"),
            Decimal("0.1526387331636337370609888628447057469502423514414"),
        ),
    ),
)
def test_existing_fast_iewma_higher_target_solver_and_cost_golden_remain_unchanged(
    target_volatility: Decimal,
    expected_scalar: Decimal,
    expected_post_nav: Decimal,
    expected_cost: Decimal,
    expected_cash: Decimal,
) -> None:
    result, panel, scalar = _run_reconciliation_regression(target_volatility)
    second = result.rebalances[1]
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        desired_values = allocation_backtest_module._desired_values(
            second.target,
            second.post_trade_nav,
        )
        actual_stock_total = sum(
            (
                (value / price) * price
                for value, price in zip(
                    desired_values,
                    panel.open_prices[2],
                    strict=True,
                )
            ),
            Decimal(0),
        )
        expected_actual_cash = second.post_trade_nav - actual_stock_total
        expected_reconciled_nav = second.pre_trade_nav - second.transaction_cost
        exact_weight_total = (
            sum(second.realized_weights, Decimal(0)) + second.realized_cash_weight
        )

    assert scalar == expected_scalar
    assert second.post_trade_nav == expected_post_nav
    assert second.transaction_cost == expected_cost
    assert second.cash_after == expected_cash
    assert second.cash_after == expected_actual_cash
    assert second.post_trade_nav == expected_reconciled_nav
    assert exact_weight_total == Decimal(1)


def test_fast_iewma_reconciliation_with_zero_cost_preserves_nav_and_cash_flow() -> None:
    result, panel, _ = _run_reconciliation_regression(
        Decimal("0.15"),
        buy_cost_rate=Decimal(0),
        sell_cost_rate=Decimal(0),
    )
    second = result.rebalances[1]

    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        desired_values = allocation_backtest_module._desired_values(
            second.target,
            second.post_trade_nav,
        )
        quantities = tuple(
            value / price
            for value, price in zip(desired_values, panel.open_prices[2], strict=True)
        )
        actual_stock_total = sum(
            (
                quantity * price
                for quantity, price in zip(
                    quantities,
                    panel.open_prices[2],
                    strict=True,
                )
            ),
            Decimal(0),
        )
        expected_cash_after = second.post_trade_nav - actual_stock_total
        exact_weight_total = (
            sum(second.realized_weights, Decimal(0)) + second.realized_cash_weight
        )

    assert second.pre_trade_nav == Decimal(
        "1.8498475591377288492383124839957729374324985981881"
    )
    assert second.post_trade_nav == second.pre_trade_nav
    assert second.transaction_cost == 0
    assert second.cash_after == Decimal(
        "1.0012802894944838536074110367098467502968283462966"
    )
    assert second.cash_after == expected_cash_after
    assert exact_weight_total == Decimal(1)


def test_realized_weight_nav_reconciliation_accepts_one_ulp_and_rejects_two() -> None:
    context = Context(prec=50, rounding=ROUND_HALF_EVEN)
    with localcontext(context):
        nav = Decimal(1)
        stock_values = (Decimal("0.2"),)
        stock_total = stock_values[0]
        one_ulp_cash = context.next_plus(nav) - stock_total
        weights, cash_weight = allocation_backtest_module._realized_weights(
            stock_values,
            stock_total,
            one_ulp_cash,
            nav,
            context,
        )
        two_ulp_cash = context.next_plus(context.next_plus(nav)) - stock_total

        with pytest.raises(AllocationSelfFinancingError, match="1 Decimal ULP"):
            allocation_backtest_module._realized_weights(
                stock_values,
                stock_total,
                two_ulp_cash,
                nav,
                context,
            )

    assert sum(weights, Decimal(0)) + cash_weight == Decimal(1)


@pytest.mark.parametrize(
    ("stock_values", "stock_total", "cash", "nav"),
    (
        ((Decimal("0.5"),), Decimal("0.5"), Decimal("-0.1"), Decimal("0.4")),
        ((Decimal("-0.1"),), Decimal("-0.1"), Decimal("1.1"), Decimal(1)),
        ((Decimal("NaN"),), Decimal("0.5"), Decimal("0.5"), Decimal(1)),
        ((Decimal("-Infinity"),), Decimal("0.5"), Decimal("0.5"), Decimal(1)),
        ((Decimal("0.5"),), Decimal("Infinity"), Decimal("0.5"), Decimal(1)),
        ((Decimal("0.5"),), Decimal("0.5"), Decimal("NaN"), Decimal(1)),
        ((Decimal("0.5"),), Decimal("0.5"), Decimal("0.5"), Decimal("Infinity")),
    ),
)
def test_realized_weight_reconciliation_rejects_negative_or_nonfinite_values(
    stock_values: tuple[Decimal, ...],
    stock_total: Decimal,
    cash: Decimal,
    nav: Decimal,
) -> None:
    context = Context(prec=50, rounding=ROUND_HALF_EVEN)

    with pytest.raises(AllocationSelfFinancingError):
        allocation_backtest_module._realized_weights(
            stock_values,
            stock_total,
            cash,
            nav,
            context,
        )


def test_nav_ulp_calculation_fails_closed_when_next_value_is_infinite() -> None:
    context = Context(prec=2, rounding=ROUND_HALF_EVEN, Emax=1, Emin=-1)

    with pytest.raises(AllocationSelfFinancingError, match=r"ULP.*양의 유한"):
        allocation_backtest_module._nav_ulp(Decimal("99"), context)


def test_target_value_underflow_is_rejected_before_phantom_holdings_can_succeed() -> None:
    extreme_price = Decimal((0, (1,), 1_000_050))
    panel = AlignedPricePanel(
        stock_codes=("000001", "000002"),
        dates=(date(2026, 1, 1), date(2026, 1, 2)),
        open_prices=((extreme_price, extreme_price),) * 2,
        close_prices=((extreme_price, extreme_price),) * 2,
    )
    target = AllocationTarget(
        signal_date=panel.dates[0],
        stock_codes=panel.stock_codes,
        target_weights=(Decimal("0.4"), Decimal("0.4")),
        policy_id="underflow_probe",
        target_equity_weight=Decimal("0.8"),
    )

    with pytest.raises(AllocationSelfFinancingError, match="underflow"):
        run_allocation_backtest_with_dynamic_targets(
            panel,
            "underflow_probe",
            (ScheduledAllocationTarget(1, target),),
            AllocationBacktestConfig(),
            annual_cash_yield=Decimal(0),
        )


def test_self_financing_failure_carries_the_failing_signal_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel = _panel(
        tuple((Decimal("100"),) for _ in range(3)),
        stock_codes=("005930",),
    )
    schedule = (_scheduled_target(panel, 1, Decimal("0.5")),)

    def fail_execution(*args: object, **kwargs: object) -> None:
        raise AllocationSelfFinancingError("APP_SECRET=must-not-escape")

    monkeypatch.setattr(allocation_backtest_module, "_execute_target", fail_execution)

    with pytest.raises(AllocationSelfFinancingError) as caught:
        run_allocation_backtest_with_dynamic_targets(
            panel,
            "dynamic_equity_target",
            schedule,
            AllocationBacktestConfig(),
            annual_cash_yield=Decimal(0),
        )

    assert caught.value.as_of_date == panel.dates[0]


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
