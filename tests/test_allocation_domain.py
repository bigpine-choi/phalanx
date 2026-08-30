from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from phalanx.domain import (
    AlignedPricePanel,
    AllocationBacktestConfig,
    AllocationBacktestResult,
    AllocationPolicyInput,
    AllocationTarget,
)
from phalanx.portfolio.allocation_backtest import run_allocation_backtest
from phalanx.portfolio.allocation_policies import WeeklyEqualWeight
from phalanx.portfolio.errors import (
    InvalidAlignedPricePanelError,
    InvalidAllocationBacktestConfigError,
    InvalidAllocationBacktestResultError,
    InvalidAllocationPolicyInputError,
    InvalidAllocationRebalanceError,
    InvalidAllocationTargetError,
)


def _target(**overrides: object) -> AllocationTarget:
    values: dict[str, object] = {
        "signal_date": date(2026, 1, 5),
        "stock_codes": ("005930", "000660"),
        "target_weights": (Decimal("0.5"), Decimal("0.495")),
        "policy_id": "weekly_equal_weight",
        "target_equity_weight": Decimal("0.995"),
    }
    values.update(overrides)
    return AllocationTarget(**values)  # type: ignore[arg-type]


def _panel(**overrides: object) -> AlignedPricePanel:
    values: dict[str, object] = {
        "stock_codes": ("005930", "000660"),
        "dates": (date(2026, 1, 2), date(2026, 1, 5)),
        "open_prices": (
            (Decimal("100"), Decimal("200")),
            (Decimal("101"), Decimal("198")),
        ),
        "close_prices": (
            (Decimal("101"), Decimal("199")),
            (Decimal("102"), Decimal("197")),
        ),
    }
    values.update(overrides)
    return AlignedPricePanel(**values)  # type: ignore[arg-type]


def _result() -> AllocationBacktestResult:
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(5))
    prices = tuple((Decimal(100 + index),) for index in range(5))
    return run_allocation_backtest(
        AlignedPricePanel(
            stock_codes=("005930",),
            dates=dates,
            open_prices=prices,
            close_prices=prices,
        ),
        WeeklyEqualWeight(),
        AllocationBacktestConfig(
            minimum_training_returns=2,
            maximum_training_returns=2,
            rebalance_interval=5,
        ),
    )


def test_allocation_target_and_price_panel_are_frozen_and_preserve_decimal_values() -> None:
    target = _target()
    panel = _panel()

    assert target.target_weights == (Decimal("0.5"), Decimal("0.495"))
    assert panel.stock_codes == ("005930", "000660")
    assert panel.open_prices[0] == (Decimal("100"), Decimal("200"))
    with pytest.raises(FrozenInstanceError):
        target.policy_id = "changed"
    with pytest.raises(FrozenInstanceError):
        panel.dates = ()


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"stock_codes": ()}, "최소 1개"),
        ({"stock_codes": ("005930", "005930")}, "중복"),
        ({"stock_codes": ("5930", "000660")}, "6자리"),
        ({"target_weights": (Decimal("0.995"),)}, "수는 종목코드 수"),
        (
            {"target_weights": (Decimal("NaN"), Decimal("0.495"))},
            "유한한 Decimal",
        ),
        (
            {"target_weights": (Decimal("-0.1"), Decimal("1.095"))},
            "0 이상의",
        ),
        (
            {"target_weights": (Decimal("0.5"), Decimal("0.49"))},
            "합계",
        ),
        ({"target_equity_weight": Decimal("0")}, "0 초과"),
        ({"policy_id": " "}, "정책 식별자"),
    ),
)
def test_allocation_target_rejects_invalid_codes_weights_and_policy(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(InvalidAllocationTargetError, match=message):
        _target(**overrides)


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"stock_codes": ()}, "최소 1개"),
        ({"stock_codes": ("005930", "005930")}, "중복"),
        (
            {"dates": (date(2026, 1, 2), date(2026, 1, 2))},
            "중복",
        ),
        (
            {"dates": (date(2026, 1, 5), date(2026, 1, 2))},
            "오름차순",
        ),
        ({"open_prices": ((Decimal("100"), Decimal("200")),)}, "행 수"),
        (
            {
                "close_prices": (
                    (Decimal("101"),),
                    (Decimal("102"),),
                )
            },
            "열 수",
        ),
        (
            {
                "open_prices": (
                    (Decimal("0"), Decimal("200")),
                    (Decimal("101"), Decimal("198")),
                )
            },
            "양의 유한한 Decimal",
        ),
    ),
)
def test_aligned_price_panel_rejects_invalid_dimensions_dates_codes_and_prices(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(InvalidAlignedPricePanelError, match=message):
        _panel(**overrides)


def test_allocation_backtest_config_has_the_fixed_mvp_defaults_and_is_frozen() -> None:
    config = AllocationBacktestConfig()

    assert config.minimum_training_returns == 504
    assert config.maximum_training_returns == 756
    assert config.rebalance_interval == 5
    assert config.target_equity_weight == Decimal("0.995")
    assert config.buy_cost_rate == Decimal("0.001")
    assert config.sell_cost_rate == Decimal("0.0025")
    assert config.annualization_trading_days == 252
    with pytest.raises(FrozenInstanceError):
        config.rebalance_interval = 1


@pytest.mark.parametrize(
    "overrides",
    (
        {"minimum_training_returns": 0},
        {"minimum_training_returns": True},
        {"maximum_training_returns": 503},
        {"rebalance_interval": 0},
        {"target_equity_weight": Decimal("Infinity")},
        {"buy_cost_rate": Decimal("-0.001")},
        {"sell_cost_rate": Decimal("1")},
        {"annualization_trading_days": 0},
    ),
)
def test_allocation_backtest_config_rejects_invalid_settings(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(InvalidAllocationBacktestConfigError):
        AllocationBacktestConfig(**overrides)  # type: ignore[arg-type]


def test_policy_input_rejects_a_future_or_misaligned_return_window() -> None:
    with pytest.raises(InvalidAllocationPolicyInputError, match=r"마지막.*신호일"):
        AllocationPolicyInput(
            signal_date=date(2026, 1, 5),
            signal_number=0,
            stock_codes=("005930",),
            return_dates=(date(2026, 1, 6),),
            return_values=((Decimal("0.01"),),),
        )


def test_backtest_result_and_rebalance_record_are_frozen() -> None:
    result = _result()

    with pytest.raises(FrozenInstanceError):
        result.net_asset_values = ()
    with pytest.raises(FrozenInstanceError):
        result.rebalances[0].cash_after = Decimal(0)


def test_backtest_result_rejects_reverse_dates_nonfinite_nav_and_negative_costs() -> None:
    result = _result()

    with pytest.raises(InvalidAllocationBacktestResultError, match="오름차순"):
        replace(result, dates=tuple(reversed(result.dates)))
    with pytest.raises(InvalidAllocationBacktestResultError, match="NAV"):
        replace(
            result,
            net_asset_values=tuple(Decimal("NaN") for _ in result.net_asset_values),
        )
    with pytest.raises(InvalidAllocationBacktestResultError, match="음수가 아닌"):
        replace(result, cumulative_transaction_cost=Decimal("-0.01"))


def test_rebalance_record_rejects_negative_cash_or_broken_nav_cost_reconciliation() -> None:
    record = _result().rebalances[0]

    with pytest.raises(InvalidAllocationRebalanceError, match="현금"):
        replace(record, cash_after=Decimal("-0.01"))
    with pytest.raises(InvalidAllocationRebalanceError, match="차감한 값"):
        replace(record, post_trade_nav=record.pre_trade_nav)
