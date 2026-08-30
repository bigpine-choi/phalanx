from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from phalanx.domain import (
    ALLOCATION_RESEARCH_SCOPE,
    AllocationBacktestConfig,
    AllocationPolicyInput,
    AllocationPolicyOutcomeStatus,
    AllocationTarget,
    AllocationTrialStatus,
    DailyBar,
    KoreanStock,
    StockMarket,
)
from phalanx.market_data.service import StockDailyBars
from phalanx.portfolio.allocation_policies import WeeklyEqualWeight
from phalanx.portfolio.allocation_research import conduct_allocation_research
from phalanx.portfolio.allocation_trial_registry import serialize_allocation_trial
from phalanx.portfolio.errors import InvalidAllocationResearchTrialError


def _histories(count: int = 12) -> tuple[StockDailyBars, ...]:
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(count))
    histories: list[StockDailyBars] = []
    for stock_code, stock_name, start_price, up, down in (
        ("005930", "삼성전자", Decimal("100"), Decimal("1.02"), Decimal("0.99")),
        ("000660", "SK하이닉스", Decimal("200"), Decimal("1.01"), Decimal("0.98")),
    ):
        price = start_price
        bars: list[DailyBar] = []
        for index, trade_date in enumerate(dates):
            if index:
                price *= up if index % 2 else down
            bars.append(
                DailyBar(
                    stock_code=stock_code,
                    trade_date=trade_date,
                    open_price=price,
                    high_price=price,
                    low_price=price,
                    close_price=price,
                    volume=1000,
                )
            )
        histories.append(
            StockDailyBars(
                KoreanStock(stock_code, stock_name, StockMarket.KOSPI),
                tuple(bars),
            )
        )
    return tuple(histories)


class SecretFailingPolicy:
    policy_id = "secret_failing_policy"
    policy_version = "1"

    def __init__(self, secret: str) -> None:
        self._secret = secret

    def should_rebalance(self, signal_number: int) -> bool:
        return True

    def build_target(
        self,
        policy_input: AllocationPolicyInput,
        target_equity_weight: Decimal,
    ) -> AllocationTarget:
        raise RuntimeError(self._secret)


class LateStartPolicy:
    policy_id = "late_start_policy"
    policy_version = "1"

    def should_rebalance(self, signal_number: int) -> bool:
        return signal_number > 0

    def build_target(
        self,
        policy_input: AllocationPolicyInput,
        target_equity_weight: Decimal,
    ) -> AllocationTarget:
        first_weight = target_equity_weight / Decimal(len(policy_input.stock_codes))
        leading = tuple(first_weight for _ in policy_input.stock_codes[:-1])
        return AllocationTarget(
            signal_date=policy_input.signal_date,
            stock_codes=policy_input.stock_codes,
            target_weights=(
                *leading,
                target_equity_weight - sum(leading, Decimal(0)),
            ),
            policy_id=self.policy_id,
            target_equity_weight=target_equity_weight,
        )


def _config() -> AllocationBacktestConfig:
    return AllocationBacktestConfig(
        minimum_training_returns=3,
        maximum_training_returns=5,
        rebalance_interval=2,
    )


def test_conducts_all_default_policies_on_one_ordered_conditional_trial() -> None:
    trial = conduct_allocation_research(
        _histories(),
        date(2026, 1, 1),
        date(2026, 1, 12),
        config=_config(),
        trial_id_factory=lambda: "deterministic-trial",
        clock=lambda: datetime(2026, 1, 13, tzinfo=UTC),
    )

    assert trial.status is AllocationTrialStatus.SUCCEEDED
    assert trial.stock_codes == ("005930", "000660")
    assert tuple(outcome.policy_id for outcome in trial.policy_outcomes) == (
        "weekly_equal_weight",
        "weekly_inverse_volatility",
        "equal_weight_buy_and_hold",
    )
    assert all(
        outcome.status is AllocationPolicyOutcomeStatus.SUCCEEDED
        for outcome in trial.policy_outcomes
    )
    assert trial.actual_evaluation_start == date(2026, 1, 5)
    assert trial.actual_evaluation_end == date(2026, 1, 12)
    assert trial.research_scope == ALLOCATION_RESEARCH_SCOPE
    assert trial.code_model_version == "allocation-research-v1"


def test_fingerprints_do_not_depend_on_trial_id_or_execution_time() -> None:
    first = conduct_allocation_research(
        _histories(),
        date(2026, 1, 1),
        date(2026, 1, 12),
        config=_config(),
        trial_id_factory=lambda: "first",
        clock=lambda: datetime(2026, 1, 13, tzinfo=UTC),
    )
    second = conduct_allocation_research(
        _histories(),
        date(2026, 1, 1),
        date(2026, 1, 12),
        config=_config(),
        trial_id_factory=lambda: "second",
        clock=lambda: datetime(2027, 1, 13, tzinfo=UTC),
    )

    assert (
        first.policy_fingerprint,
        first.config_fingerprint,
        first.market_data_fingerprint,
    ) == (
        second.policy_fingerprint,
        second.config_fingerprint,
        second.market_data_fingerprint,
    )


def test_trial_is_frozen_and_rejects_result_order_or_actual_period_mismatch() -> None:
    trial = conduct_allocation_research(
        _histories(),
        date(2026, 1, 1),
        date(2026, 1, 12),
        config=_config(),
        trial_id_factory=lambda: "trial-invariants",
        clock=lambda: datetime(2026, 1, 13, tzinfo=UTC),
    )

    with pytest.raises(FrozenInstanceError):
        trial.stock_codes = ()
    with pytest.raises(InvalidAllocationResearchTrialError, match="종목 순서"):
        replace(trial, stock_codes=tuple(reversed(trial.stock_codes)))
    with pytest.raises(InvalidAllocationResearchTrialError, match="실제 평가기간"):
        replace(trial, actual_evaluation_start=date(2026, 1, 6))


def test_failed_trial_rejects_an_invented_actual_evaluation_period() -> None:
    trial = conduct_allocation_research(
        (),
        date(2026, 1, 1),
        date(2026, 1, 4),
        config=_config(),
        trial_id_factory=lambda: "failed-trial-invariants",
        clock=lambda: datetime(2026, 1, 5, tzinfo=UTC),
    )

    with pytest.raises(InvalidAllocationResearchTrialError, match="둘 수 없습니다"):
        replace(
            trial,
            actual_evaluation_start=date(2026, 1, 3),
            actual_evaluation_end=date(2026, 1, 4),
        )


def test_unknown_policy_failure_is_recorded_without_its_secret() -> None:
    secret = "synthetic-app-key-token-account-number-123"
    trial = conduct_allocation_research(
        _histories(),
        date(2026, 1, 1),
        date(2026, 1, 12),
        config=_config(),
        policies=(WeeklyEqualWeight(), SecretFailingPolicy(secret)),
        trial_id_factory=lambda: "failed-policy",
        clock=lambda: datetime(2026, 1, 13, tzinfo=UTC),
    )

    serialized = serialize_allocation_trial(trial).decode("utf-8")
    assert trial.status is AllocationTrialStatus.PARTIAL_FAILURE
    assert trial.policy_outcomes[1].status is AllocationPolicyOutcomeStatus.FAILED
    assert secret not in serialized
    assert "Traceback" not in serialized
    assert "unexpected_calculation_error" in serialized


def test_policy_with_a_late_evaluation_start_becomes_a_persistable_failure() -> None:
    trial = conduct_allocation_research(
        _histories(),
        date(2026, 1, 1),
        date(2026, 1, 12),
        config=_config(),
        policies=(WeeklyEqualWeight(), LateStartPolicy()),
        trial_id_factory=lambda: "late-start-policy",
        clock=lambda: datetime(2026, 1, 13, tzinfo=UTC),
    )

    assert trial.status is AllocationTrialStatus.PARTIAL_FAILURE
    assert trial.policy_outcomes[0].status is AllocationPolicyOutcomeStatus.SUCCEEDED
    assert trial.policy_outcomes[1].status is AllocationPolicyOutcomeStatus.FAILED
    assert trial.policy_outcomes[1].failure is not None
    assert trial.policy_outcomes[1].failure.code == "allocation_policy_error"
    assert "late_start_policy" in serialize_allocation_trial(trial).decode("utf-8")


def test_common_data_failure_records_every_policy_as_sanitized_failure() -> None:
    trial = conduct_allocation_research(
        _histories(count=4),
        date(2026, 1, 1),
        date(2026, 1, 4),
        config=AllocationBacktestConfig(
            minimum_training_returns=3,
            maximum_training_returns=5,
        ),
        trial_id_factory=lambda: "data-failure",
        clock=lambda: datetime(2026, 1, 5, tzinfo=UTC),
    )

    assert trial.status is AllocationTrialStatus.FAILED
    assert trial.actual_evaluation_start is None
    assert trial.actual_evaluation_end is None
    assert all(
        outcome.status is AllocationPolicyOutcomeStatus.FAILED for outcome in trial.policy_outcomes
    )
    assert all(
        outcome.failure is not None and outcome.failure.code == "allocation_data_error"
        for outcome in trial.policy_outcomes
    )


def test_empty_universe_is_persistable_as_a_failed_trial_without_fake_stock_codes() -> None:
    trial = conduct_allocation_research(
        (),
        date(2026, 1, 1),
        date(2026, 1, 4),
        config=_config(),
        trial_id_factory=lambda: "empty-universe",
        clock=lambda: datetime(2026, 1, 5, tzinfo=UTC),
    )

    assert trial.status is AllocationTrialStatus.FAILED
    assert trial.stock_codes == ()
    assert "allocation_data_error" in serialize_allocation_trial(trial).decode("utf-8")
